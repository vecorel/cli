from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import sys
import tarfile
import zipfile
from copy import copy
from glob import glob
from io import StringIO
from tempfile import TemporaryDirectory
from typing import Any, Callable, Generator, Optional, Sequence

import geopandas as gpd
import multivolumefile
import numpy as np
import pandas as pd
import py7zr
import rarfile
from fsspec import AbstractFileSystem
from fsspec.implementations.local import LocalFileSystem
from geopandas import GeoDataFrame

from ..cli.logger import LoggerMixin
from ..cli.util import display_pandas_unrestricted
from ..encoding.geojson import READ_ENCODING
from ..encoding.geoparquet import GeoParquet
from ..vecorel.collection import Collection
from ..vecorel.hilbert import hilbert_sort_geodataframe
from ..vecorel.schemas import Schemas
from ..vecorel.typing import Sources
from ..vecorel.util import get_fs, name_from_uri, stream_file
from .flatdict import FlatDict


class BaseConverter(LoggerMixin):
    command = None

    bbox: Optional[tuple[float]] = None
    id: str = ""
    short_name: str = ""
    title: str = ""
    license: Optional[str] = None
    attribution: Optional[str] = None
    description: str = ""
    provider: Optional[str] = None

    sources: Optional[Sources] = None
    data_access: str = ""
    open_options: dict = {}
    avoid_range_request: bool = False
    variants: dict[str, Sources] = {}
    variant: Optional[str] = None

    columns: dict[str, str | Sequence[str]] = {}
    column_additions: dict[str, str] = {}
    column_filters: dict[str, Callable] = {}
    column_migrations: dict[str, Callable] = {}
    missing_schemas: dict[str, Any] = {}
    extensions: set[str] = set()

    index_as_id: bool = False

    # Rows with null values in schema-required properties are dropped up to this
    # share of all rows; above it the conversion fails. Rows with an empty or
    # missing geometry are always dropped, regardless of this share.
    max_dropped_share: float = 0.01

    # Move properties that hold one value for every row into the collection metadata.
    # A conversion that writes one part of a dataset must not: "one value for every
    # row" is then judged over the part rather than over the dataset, so a property
    # that varies between parts is lost.
    dehydrate: bool = True

    def __init__(self, *args, **kwargs):
        super().__init__()

        # In BaseConverter and mixins we use class-based members as instance based-members
        # Every instance should be allowed to modify its member attributes, so here we make a copy of dicts/lists
        for key, item in inspect.getmembers(self):
            if not key.startswith("_") and isinstance(item, (list, dict, set)):
                setattr(self, key, copy(item))

    def _require_one_source_of_urls(self):
        """Fail when both `sources` and `variants` are declared:
        `sources` wins and every `--variant` would silently convert the same file."""
        if self.sources and self.variants:
            raise ValueError(
                f"{type(self).__name__} declares both sources and variants; sources wins "
                "and every --variant would convert the same file. Drop sources, or set "
                "variants = {} when the inherited ones do not apply."
            )

    def select_variant(self, variant: Optional[str]) -> None:
        """Store the requested variant; without one, the default variant is used.
        Done at the start of convert() rather than in get_urls(), so a converter that
        overrides get_urls() does not have to repeat the default, and so the default is
        also set when the user supplies the input files."""
        self.variant = variant
        if self.variants and self.variant is None:
            self.variant = self.default_variant()
            opts = ", ".join(self.variants)
            self.warning(f"No variant given, choosing {self.variant} from {opts}")

    def default_variant(self) -> str:
        """The latest year when the variants are years, otherwise the first declared."""
        keys = list(self.variants)
        if all(re.fullmatch(r"\d{4}", key) for key in keys):
            return max(keys)
        return keys[0]

    def _check_id_mapping(self):
        """Warn before converting when nothing is mapped to the required `id` property.
        Unmapped columns are dropped, which also removes the column filled by
        `index_as_id` unless the converter maps `"id": "id"`."""
        targets = set()
        for value in list(self.columns.values()) + list(self.column_additions or {}):
            targets.update(value if isinstance(value, (list, tuple)) else [value])
        if "id" not in targets:
            hint = (
                ' — `index_as_id = True` is set, so add \'"id": "id"\' to columns'
                if self.index_as_id
                else " — map a unique source column to it, or set index_as_id = True"
                ' and add \'"id": "id"\' to columns'
            )
            self.warning(f"{type(self).__name__} maps no column to 'id'{hint}")

    def _check_unique_ids(self, gdf, columns):
        """Warn when the column that becomes `id` does not identify a feature.
        Runs before geometries are exploded, so it judges what the converter
        assigned rather than the split parts of one source feature. Null ids
        are not counted here; they are dropped under a bounded rule afterwards.
        """
        sources = [
            k for k, v in columns.items() if "id" in (v if isinstance(v, (list, tuple)) else [v])
        ]
        column = next(
            (c for c in sources if c in gdf.columns), "id" if "id" in gdf.columns else None
        )
        if column is None:
            self.warning(
                f"{type(self).__name__}: none of the columns mapped to 'id' "
                f"({', '.join(sources) or 'none'}) is in this source; it has "
                f"{', '.join(sorted(gdf.columns)[:12])}"
            )
            return
        ids = gdf[column].dropna()
        if ids.is_unique:
            return
        counts = ids.value_counts()
        duplicated = int(len(ids) - len(counts))
        worst = int(counts.iloc[0])
        self.warning(
            f"{type(self).__name__}: '{column}' is not unique — {duplicated:,} of {len(ids):,} "
            f"rows repeat an id (one appears {worst:,} times), so it cannot be `id`. Map a column "
            "that identifies a feature, build one from the source's key columns, or use the row "
            "index (index_as_id) only when the conversion reads a single file."
        )

    def _drop_incomplete_rows(self, gdf, columns):
        """Drop rows that can never validate. Rows with null values in a
        schema-required property are dropped up to ``max_dropped_share``;
        above it the conversion fails, as quietly dropping large parts of a
        dataset would hide that the converter needs fixing (and the writer
        rejects nulls in the non-nullable required fields anyway). Rows with
        an empty or missing geometry are always dropped: they cannot survive
        the geometry processing anyway and would break the Hilbert sort."""
        collection = self.create_collection(self.id.strip())
        schemas = collection.merge_schemas({})
        collection_only = set(collection.get_collection_only_properties())
        required = [
            r for r in schemas.get("required", []) if r != "geometry" and r not in collection_only
        ]

        # One combined mask, so max_dropped_share bounds the total share
        invalid = pd.Series(False, index=gdf.index)
        reasons = []

        # This runs before columns are renamed, so look up the source column
        for key in required:
            for src, dst in columns.items():
                targets = dst if isinstance(dst, (list, tuple)) else [dst]
                if key in targets and src in gdf.columns:
                    nulls = gdf[src].isna()
                    if nulls.any():
                        reasons.append(f"{int(nulls.sum())} without a value for {key} ({src})")
                        invalid |= nulls

        if invalid.any():
            share = invalid.mean()
            details = "; ".join(reasons)
            if share > self.max_dropped_share:
                raise ValueError(
                    f"{int(invalid.sum())} of {len(gdf)} rows ({share:.1%}) have no value for "
                    f"a required property ({details}); fix the converter instead of dropping them"
                )
            self.warning(
                f"Dropping {int(invalid.sum())} of {len(gdf)} rows that can never "
                f"validate ({details})"
            )
            gdf = gdf[~invalid]

        if gdf.active_geometry_name is not None:
            geom = gdf.geometry
            blank = geom.isna() | geom.is_empty
            if blank.any():
                share = blank.mean()
                message = (
                    f"Dropping {int(blank.sum())} of {len(gdf)} rows with an empty "
                    f"or missing geometry"
                )
                if share > self.max_dropped_share:
                    message += f" ({share:.1%}, exceeds max_dropped_share) — fix the converter"
                self.warning(message)
                gdf = gdf[~blank]

        return gdf

    def _prewarm_schemas(self):
        """Fetch every schema this conversion will need upfront, with retries,
        so a transient schema-host blip cannot kill the conversion at the very
        last step. load_file caches per process."""
        import time

        from ..vecorel.util import load_file

        uris = set(self.extensions)
        uris.add(Schemas.get_core_uri())
        attempts = 8
        for uri in sorted(uris):
            for attempt in range(attempts):
                try:
                    load_file(uri)
                    break
                except Exception as e:
                    if attempt == attempts - 1:
                        raise RuntimeError(
                            f"Cannot load schema {uri} after {attempts} attempts: {e}"
                        ) from e
                    self.warning(f"Schema fetch failed ({uri}), retrying: {str(e)[:100]}")
                    # ~4 min of tolerance: schema host outages have outlasted a 30 s budget
                    time.sleep(min(2**attempt * 2, 60))

    def migrate(self, gdf) -> GeoDataFrame:
        return gdf

    def file_migration(
        self, gdf: GeoDataFrame, path: str, uri: str, layer: Optional[str] = None
    ) -> GeoDataFrame:  # noqa
        return gdf

    def layer_filter(self, layer: str, uri: str) -> bool:
        return True

    def post_migrate(self, gdf: GeoDataFrame) -> GeoDataFrame:
        return gdf

    def get_columns(self, gdf: GeoDataFrame) -> dict[str, str | Sequence[str]]:
        return self.columns.copy()

    def get_cache(self, cache_folder=None, **kwargs) -> tuple[AbstractFileSystem, str]:
        if cache_folder is None:
            _kwargs = {}
            if sys.version_info.major >= 3 and sys.version_info.minor >= 12:
                _kwargs["delete"] = False  # only available in Python 3.12 and later
            with TemporaryDirectory(**_kwargs) as tmp_folder:
                cache_folder = tmp_folder

        cache_fs = get_fs(cache_folder, **kwargs)
        if not cache_fs.exists(cache_folder):
            cache_fs.makedirs(cache_folder)
        return cache_fs, cache_folder

    def download_files(self, uris, cache_folder=None, **kwargs):
        """Download (and cache) files from various sources"""
        if isinstance(uris, str):
            uris = {uris: name_from_uri(uris)}

        if self.avoid_range_request and "block_size" not in kwargs:
            kwargs["block_size"] = 0

        # Multi-volume 7z archives (.7z.001, .7z.002, ...) are one 7z stream split
        # across several URIs; they must be downloaded and extracted together.
        uris, volume_groups = self._group_multivolume_7z(uris)

        paths = []
        for group in volume_groups.values():
            paths.extend(self._download_multivolume_7z(group, cache_folder, **kwargs))

        for uri, target in uris.items():
            is_archive = isinstance(target, list)
            if is_archive:
                name = name_from_uri(uri)
                # if there's no file extension, it's likely a folder, which may not be unique
                if "." not in name:
                    name = hashlib.sha256(uri.encode()).hexdigest()
            else:
                name = target

            source_fs = get_fs(uri, **kwargs)
            cache_fs, cache_folder = self.get_cache(cache_folder)

            if isinstance(source_fs, LocalFileSystem):
                cache_file = uri
            else:
                cache_file = os.path.join(cache_folder, name)

            zip_folder = os.path.join(cache_folder, "extracted." + os.path.splitext(name)[0])
            must_extract = is_archive and not os.path.exists(zip_folder)

            if (not is_archive or must_extract) and not cache_fs.exists(cache_file):
                self._download_file(source_fs, uri, cache_fs, cache_file)

            if must_extract:
                if zipfile.is_zipfile(cache_file):
                    try:
                        with zipfile.ZipFile(cache_file, "r") as zip_file:
                            zip_file.extractall(zip_folder)
                    except NotImplementedError as e:
                        if str(e) != "That compression method is not supported":
                            raise e
                        import zipfile_deflate64

                        with zipfile_deflate64.ZipFile(cache_file, "r") as zip_file:
                            zip_file.extractall(zip_folder)
                elif py7zr.is_7zfile(cache_file):
                    with py7zr.SevenZipFile(cache_file, "r") as sz_file:
                        sz_file.extractall(zip_folder)
                elif rarfile.is_rarfile(cache_file):
                    with rarfile.RarFile(cache_file, "r") as w:
                        w.extractall(zip_folder)
                elif tarfile.is_tarfile(cache_file):
                    with tarfile.open(cache_file, "r") as w:
                        w.extractall(zip_folder)
                else:
                    raise ValueError(
                        f"Only ZIP and 7Z files are supported for extraction, fails for: {cache_file}"
                    )

            if is_archive:
                for filename in target:
                    paths.append((os.path.join(zip_folder, filename), uri))
            else:
                paths.append((cache_file, uri))

        return paths

    @staticmethod
    def _download_file(source_fs, uri, cache_fs, cache_file):
        """Stream a remote file into the cache.

        The data goes to a `.part` file that is renamed only after a clean close,
        so an interrupted download leaves nothing that a later run could mistake
        for a cached file.
        """
        part_file = cache_file + ".part"
        try:
            with cache_fs.open(part_file, mode="wb") as file:
                stream_file(source_fs, uri, file)
        except BaseException:
            try:
                cache_fs.rm(part_file)
            except FileNotFoundError:
                pass
            raise
        cache_fs.mv(part_file, cache_file)

    @staticmethod
    def _group_multivolume_7z(uris):
        """Split URIs into the regular ones and the multi-volume 7z parts
        (.7z.001, .7z.002, ...), grouping the parts that belong to one archive
        (same URI up to the volume number). Returns (regular, groups) where
        groups maps the archive URI (without the volume suffix) to its parts.
        """
        regular = {}
        groups = {}
        for uri, target in uris.items():
            # the parts of a multi-volume archive are given archive-style, with a
            # list of target paths (the plain-string download below is not grouped)
            if isinstance(target, list) and re.search(r"\.7z\.\d{3}$", uri):
                archive = re.sub(r"\.\d{3}$", "", uri)
                groups.setdefault(archive, {})[uri] = target
            else:
                regular[uri] = target
        return regular, groups

    def _download_multivolume_7z(self, volumes, cache_folder=None, **kwargs):
        """Download and extract a multi-volume 7z archive. The parts (.7z.001,
        .7z.002, ...) form one 7z stream; py7zr reads them together through
        multivolumefile, so they are downloaded as plain files and extracted in
        one go. Only the parts that carry target paths contribute output files.
        """
        # download the parts as plain files; the returned paths locate the cache,
        # which get_cache() cannot on its own when cache_folder is a temp directory
        parts = self.download_files(
            {uri: name_from_uri(uri) for uri in volumes}, cache_folder, **kwargs
        )
        _, cache_folder = self.get_cache(cache_folder)
        first = next(iter(volumes))
        archive = re.sub(r"\.\d{3}$", "", parts[0][0])  # <path>/<name>.7z.001 -> .7z
        name = os.path.basename(archive)
        folder = os.path.join(cache_folder, "extracted." + os.path.splitext(name)[0])
        if not os.path.exists(folder):
            self.info(f"Extracting {len(volumes)} volumes of {name}")
            with multivolumefile.MultiVolume(archive, mode="rb", ext_digits=3) as volume:
                with py7zr.SevenZipFile(volume, "r") as sz_file:
                    sz_file.extractall(folder)
        targets = next((volumes[uri] for uri in volumes if volumes[uri]), [])
        return [(os.path.join(folder, target), first) for target in targets]

    def get_urls(self):
        urls = self.sources
        if not urls and self.variants:
            # the default variant is chosen in convert(), see select_variant()
            if self.variant in self.variants:
                urls = self.variants[self.variant]
            else:
                opts = ", ".join(self.variants)
                raise ValueError(f"Unknown variant '{self.variant}', choose from {opts}")
        return urls

    def get_data(
        self, paths: list[tuple[str, str]], **kwargs
    ) -> Generator[tuple[GeoDataFrame, str, str, Optional[str]]]:
        for path, uri in paths:
            # e.g. allow "*.shp" to identify the single relevant file without knowing the name in advance
            if "*" in path:
                lst = glob(path, recursive=True)
                assert len(lst) == 1, f"Can not match {path} to a single file"
                path = lst[0]
            self.info(f"Reading {path} into GeoDataFrame(s)")
            is_parquet = path.endswith(".parquet") or path.endswith(".geoparquet")
            is_json = path.endswith(".json") or path.endswith(".geojson")
            layers = [None]
            # Parquet and geojson don't support layers
            if not (is_parquet or is_json):
                all_layers = gpd.list_layers(path)
                layers = [
                    layer for layer in all_layers["name"] if self.layer_filter(str(layer), path)
                ]
                if len(layers) == 0:
                    self.warning("No layers left for layering after filtering")

            for layer in layers:
                if layer is not None:
                    kwargs["layer"] = layer
                    self.info(f"Reading layer {layer} into GeoDataFrame", indent="- ")

                if is_parquet:
                    data = gpd.read_parquet(path, **kwargs)
                elif is_json:
                    data = self.read_geojson(path, **kwargs)
                else:
                    data = gpd.read_file(path, **kwargs)

                yield GeoDataFrame(data), path, uri, layer

    def read_geojson(self, path, **kwargs):
        # open_options is shared with gpd.read_parquet() and gpd.read_file(), so a converter
        # cannot set a default encoding there without breaking the other two readers.
        kwargs.setdefault("encoding", READ_ENCODING)
        with open(path, **kwargs) as f:
            obj = json.load(f)

        if not isinstance(obj, dict):
            raise ValueError("JSON file must contain a GeoJSON object")
        elif obj["type"] != "FeatureCollection":
            raise ValueError("JSON file must contain a GeoJSON FeatureCollection")

        obj["features"] = list(map(self._normalize_geojson_properties, obj["features"]))

        return GeoDataFrame.from_features(obj, crs="EPSG:4326")

    def _normalize_geojson_properties(self, feature):
        # Convert properties of type dict to dot notation
        feature["properties"] = FlatDict(feature["properties"], delimiter=".")

        # Preserve id: https://github.com/geopandas/geopandas/issues/1208
        if "id" not in feature["properties"]:
            feature["properties"]["id"] = feature["id"]

        return feature

    def read_data(self, paths, **kwargs):
        gdfs = []
        for data, path, uri, layer in self.get_data(paths, **kwargs):
            # 0. Run migration per file/layer
            data = self.file_migration(data, path, uri, layer)
            if not isinstance(data, GeoDataFrame):
                raise ValueError("Per-file/layer migration function must return a GeoDataFrame")
            gdfs.append(data)

        return pd.concat(gdfs)

    def filter_rows(self, gdf):
        if len(self.column_filters) > 0:
            self.info("Applying filters")
            for key, fn in self.column_filters.items():
                if key in gdf.columns:
                    result = fn(gdf[key])
                    # If the result is a tuple, the second value is a flag to potentially invert the mask
                    if isinstance(result, tuple):
                        if result[1]:
                            # Invert mask
                            mask = ~result[0]
                        else:
                            # Use mask as is
                            mask = result[0]
                    else:
                        # Just got a mask, proceed
                        mask = result

                    # Filter columns based on the mask
                    gdf = gdf[mask]
                else:
                    self.warning(f"Column '{key}' not found in dataset, skipping filter")
        return gdf

    def get_title(self):
        title = self.title.strip()
        return f"{title} ({self.variant})" if self.variant else title

    def create_collection(self, cid) -> Collection:
        schema_uris = [Schemas.get_core_uri()]
        schema_uris.extend(self.extensions)
        collection = Collection(
            {
                "schemas": {cid: schema_uris},
                "title": self.get_title(),
                "description": self.description.strip(),
                "license": self.license,
                "provider": self.provider,
                "attribution": self.attribution,
            }
        )
        collection.set_custom_schemas(self.missing_schemas)
        return collection

    def convert(
        self,
        output_file,
        cache=None,
        input_files=None,
        variant=None,
        compression=None,
        compression_level: Optional[int] = None,
        geoparquet_version=None,
        original_geometries=False,
        **kwargs,
    ) -> str:
        self.select_variant(variant)
        cid = self.id.strip()
        if self.bbox is not None and len(self.bbox) != 4:
            raise ValueError("If provided, the bounding box must consist of 4 numbers")

        self._check_id_mapping()
        self._require_one_source_of_urls()
        self._prewarm_schemas()

        # Create output folder if it doesn't exist
        directory = os.path.dirname(output_file)
        if directory:
            os.makedirs(directory, exist_ok=True)

        if input_files is not None and isinstance(input_files, dict) and len(input_files) > 0:
            self.warning("Using user provided input file(s) instead of the pre-defined file(s)")
            urls = input_files
        else:
            urls = self.get_urls()
            if urls is None:
                raise ValueError("No input files provided")

        self.info("Getting file(s) if not cached yet")
        paths = self.download_files(urls, cache)

        gdf = self.read_data(paths, **self.open_options)
        self.info("GeoDataFrame created from source(s):")
        # Make it so that everything is shown, don't output ... if there are too many columns or rows
        display_pandas_unrestricted()

        hash_before = self._hash_df(gdf.head())
        self.info(gdf.head().to_string())

        if self.index_as_id:
            gdf["id"] = gdf.index

        # 1. Run global migration
        self.info("Applying global migrations")
        gdf = self.migrate(gdf)
        assert isinstance(gdf, GeoDataFrame), "Migration function must return a GeoDataFrame"

        columns = self.get_columns(gdf)

        # 2. Run filters to remove rows that shall not be in the final data
        gdf = self.filter_rows(gdf)

        # 3. Add constant columns
        if self.column_additions:
            self.info("Adding columns")
            for key, value in self.column_additions.items():
                gdf[key] = value
                columns[key] = key

        # 4. Run column migrations
        if self.column_migrations:
            self.info("Applying column migrations")
            for key, fn in self.column_migrations.items():
                if key in gdf.columns:
                    gdf[key] = fn(gdf[key])
                else:
                    self.warning(f"Column '{key}' not found in dataset, skipping migration")

        gdf = self.post_migrate(gdf)

        self._check_unique_ids(gdf, columns)
        gdf = self._drop_incomplete_rows(gdf, columns)

        if hash_before != self._hash_df(gdf.head()):
            self.info("GeoDataFrame after migrations and filters:")
            self.info(gdf.head().to_string())

        # 5. Duplicate columns if needed
        actual_columns = {}
        for old_key, new_key in columns.items():
            if old_key in gdf.columns:
                # If the new keys are a list, duplicate the column
                if isinstance(new_key, (list, tuple)):
                    for key in new_key:
                        gdf[key] = gdf.loc[:, old_key]
                        actual_columns[key] = key
                # If the new key is a string, plan to rename the column
                elif old_key in gdf.columns:
                    actual_columns[old_key] = new_key
            # If old key is not found, remove from the schema and warn
            else:
                self.warning(f"Column '{old_key}' not found in dataset, removing from schema")

        # 6. Rename columns
        gdf.rename(columns=actual_columns, inplace=True)
        geometry_renamed = any(
            True for k, v in actual_columns.items() if v == "geometry" and k != v
        )
        if geometry_renamed:
            gdf.set_geometry("geometry", inplace=True)

        # 7. For geometry column, fix geometries
        # This was previously in step 4, but some datasets have a geometry column that is not named "geometry"
        if not original_geometries:
            gdf.geometry = gdf.geometry.make_valid()
            gdf = gdf.explode()
            gdf = gdf[np.logical_and(gdf.geometry.type == "Polygon", gdf.geometry.is_valid)]
            if gdf.geometry.array.has_z.any():
                self.info("Removing Z geometry dimension")
                gdf.geometry = gdf.geometry.force_2d()

        # Sort by Hilbert distance against the CRS's total bounds. This gives
        # row groups good spatial locality, and — crucially — produces the same
        # ordering for any independently-converted partition of the same dataset
        # (they share a CRS, therefore a Hilbert reference grid), so per-file
        # outputs can be merged later without re-sorting.
        gdf = hilbert_sort_geodataframe(gdf)

        # 8. Remove all columns that are not listed
        drop_columns = list(set(gdf.columns) - set(actual_columns.values()))
        gdf.drop(columns=drop_columns, inplace=True)

        self.info("GeoDataFrame fully migrated:")
        self.info(gdf.head().to_string())

        self.info("Creating GeoParquet file: " + str(output_file))
        columns = list(actual_columns.values())
        pq = GeoParquet(output_file)
        collection = self.create_collection(cid)
        collection["collection"] = cid
        pq.set_collection(collection)

        pq.write(
            gdf,
            properties=columns,
            dehydrate=self.dehydrate,
            compression=compression,
            compression_level=compression_level,
            geoparquet_version=geoparquet_version,
        )

        return output_file

    def __call__(self, *args, **kwargs):
        self.convert(*args, **kwargs)

    def _hash_df(self, df):
        # dataframe is unhashable, this is a simple way to create a dafaframe-hash
        buf = StringIO()
        df.info(buf=buf)
        return hash(buf.getvalue())
