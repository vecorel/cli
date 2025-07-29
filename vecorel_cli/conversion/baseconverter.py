from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import sys
import zipfile
from copy import copy
from glob import glob
from io import StringIO
from tempfile import TemporaryDirectory
from typing import Optional

import flatdict
import geopandas as gpd
import numpy as np
import pandas as pd
import py7zr
import rarfile
from fsspec.implementations.local import LocalFileSystem
from shapely.geometry import box

from ..const import STAC_TABLE_EXTENSION
from ..encoding.geoparquet import GeoParquet
from ..vecorel.util import get_fs, name_from_uri, stream_file, to_iso8601
from ..vecorel.version import vecorel_version


class BaseConverter:
    command = None

    bbox: Optional[tuple[float]] = None
    id: str = None
    short_name: str = None
    title: str = None
    license: str | dict[str, str] = None
    attribution: str = None
    description: str = None
    providers: list[dict] = []

    sources: Optional[dict[str, str] | str] = None
    source_variants: Optional[dict[dict[str, str] | str]] = None
    variant: str = None
    open_options = {}
    avoid_range_request = False
    years: Optional[dict[dict[int, str] | str]] = None
    year: str = None

    columns: dict[str, str] = {}
    column_additions: dict[str, str] = {}
    column_filters: dict[str, callable] = {}
    column_migrations: dict[str, callable] = {}
    missing_schemas: dict[str, str] = {}
    extensions: set[str] = set()

    index_as_id = False

    def __init__(self, command, **kwargs):
        self.command = command  # type: ConvertData

        # In BaseConverter and mixins we use class-based members as instance based-members
        # Every instance should be allowed to modify its member attributes, so here we make a copy of dicts/lists
        for key, item in inspect.getmembers(self):
            if not key.startswith("_") and isinstance(item, (list, dict, set)):
                setattr(self, key, copy(item))

    def log(self, text: str, status="info"):
        if self.command is not None:
            self.command.log(text, status)

    def migrate(self, gdf) -> gpd.GeoDataFrame:
        return gdf

    def file_migration(
        self, gdf: gpd.GeoDataFrame, path: str, uri: str, layer: str = None
    ) -> gpd.GeoDataFrame:  # noqa
        return gdf

    def layer_filter(self, layer: str, uri: str) -> bool:
        return True

    def post_migrate(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        return gdf

    def get_cache(self, cache_folder=None, force=False, **kwargs):
        if cache_folder is None:
            if not force:
                return None, None
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

        paths = []
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
            cache_fs, cache_folder = self.get_cache(cache_folder, force=True)

            if isinstance(source_fs, LocalFileSystem):
                cache_file = uri
            else:
                cache_file = os.path.join(cache_folder, name)

            zip_folder = os.path.join(cache_folder, "extracted." + os.path.splitext(name)[0])
            must_extract = is_archive and not os.path.exists(zip_folder)

            if (not is_archive or must_extract) and not cache_fs.exists(cache_file):
                with cache_fs.open(cache_file, mode="wb") as file:
                    stream_file(source_fs, uri, file)

            if must_extract:
                if zipfile.is_zipfile(cache_file):
                    try:
                        with zipfile.ZipFile(cache_file, "r") as zip_file:
                            zip_file.extractall(zip_folder)
                    except NotImplementedError as e:
                        if str(e) != "That compression method is not supported":
                            raise
                        import zipfile_deflate64

                        with zipfile_deflate64.ZipFile(cache_file, "r") as zip_file:
                            zip_file.extractall(zip_folder)
                elif py7zr.is_7zfile(cache_file):
                    with py7zr.SevenZipFile(cache_file, "r") as sz_file:
                        sz_file.extractall(zip_folder)
                elif rarfile.is_rarfile(cache_file):
                    with rarfile.RarFile(cache_file, "r") as w:
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

    def get_urls(self):
        urls = self.sources
        if not urls and self.years:
            opts = ", ".join([str(s) for s in self.years.keys()])
            if self.year is None:
                self.year = next(iter(self.years))
                self.warning(f"Choosing first available year {self.year} from {opts}")
            if self.year in self.years:
                urls = self.years[self.year]
            else:
                raise ValueError(f"Unknown year '{self.year}', choose from {opts}")
        return urls

    def get_data(self, paths, **kwargs):
        for path, uri in paths:
            # e.g. allow "*.shp" to identify the single relevant file without knowing the name in advance
            if "*" in path:
                lst = glob(path)
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

                yield data, path, uri, layer

    def read_geojson(self, path, **kwargs):
        with open(path, **kwargs) as f:
            obj = json.load(f)

        if not isinstance(obj, dict):
            raise ValueError("JSON file must contain a GeoJSON object")
        elif obj["type"] != "FeatureCollection":
            raise ValueError("JSON file must contain a GeoJSON FeatureCollection")

        obj["features"] = list(map(self.normalize_geojson_properties, obj["features"]))

        return gpd.GeoDataFrame.from_features(obj, crs="EPSG:4326")

    def _normalize_geojson_properties(self, feature):
        # Convert properties of type dict to dot notation
        feature["properties"] = flatdict.FlatDict(feature["properties"], delimiter=".")

        # Preserve id: https://github.com/geopandas/geopandas/issues/1208
        if "id" not in feature["properties"]:
            feature["properties"]["id"] = feature["id"]

        return feature

    def read_data(self, paths, **kwargs):
        gdfs = []
        for data, path, uri, layer in self.get_data(paths, **kwargs):
            # 0. Run migration per file/layer
            data = self.file_migration(data, path, uri, layer)
            if not isinstance(data, gpd.GeoDataFrame):
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
        return f"{title} ({self.year})" if self.year else title

    def create_collection(self, gdf, source_coop_url):
        """
        Creates a collection for the field boundary datasets.
        """
        bbox = self.bbox
        if bbox is None:
            bbox = list(
                gpd.GeoSeries([box(*gdf.total_bounds)], crs=gdf.crs).to_crs(epsg=4326).total_bounds
            )

        collection = {
            "fiboa_version": vecorel_version,
            "fiboa_extensions": list(self.extensions),
            "type": "Collection",
            "id": self.id.strip(),
            "title": self.get_title(),
            "description": self.description.strip(),
            "license": "proprietary",
            "providers": self.providers,
            "extent": {
                "spatial": {"bbox": [bbox]},
            },
            "links": [],
        }

        if "determination_datetime" in gdf.columns:
            dates = pd.to_datetime(gdf["determination_datetime"])
            min_time = to_iso8601(dates.min())
            max_time = to_iso8601(dates.max())

            collection["extent"]["temporal"] = {"interval": [[min_time, max_time]]}
            # Without temporal extent it's not valid STAC
            collection["stac_version"] = "1.0.0"

        # Add Vecorel CLI to providers
        collection["providers"].append(
            {
                "name": "Vecorel CLI",
                "roles": ["processor"],
                "url": "https://pypi.org/project/vecorel-cli",
            }
        )

        # Add source coop to providers if applicable
        if source_coop_url is not None:
            collection["providers"].append(
                {"name": "Source Cooperative", "roles": ["host"], "url": source_coop_url}
            )

        # Update attribution
        if self.attribution is not None:
            collection["attribution"] = self.attribution

        # Update license
        if isinstance(self.license, dict):
            collection["links"].append(self.license)
        elif isinstance(self.license, str):
            if self.license.lower() == "dl-de/by-2-0":
                collection["links"].append(
                    {
                        "href": "https://www.govdata.de/dl-de/by-2-0",
                        "title": "Data licence Germany - attribution - Version 2.0",
                        "type": "text/html",
                        "rel": "license",
                    }
                )
            elif self.license.lower() == "dl-de/zero-2-0":
                collection["links"].append(
                    {
                        "href": "https://www.govdata.de/dl-de/zero-2-0",
                        "title": "Data licence Germany - Zero - Version 2.0",
                        "type": "text/html",
                        "rel": "license",
                    }
                )
            elif re.match(r"^[\w\.-]+$", self.license):
                collection["license"] = self.license
            else:
                self.warning(f"Invalid license identifier: {self.license}")
        else:
            self.warning("License information missing")

        return collection

    def convert(
        self,
        output_file,
        cache=None,
        input_files=None,
        source_coop_url=None,
        store_collection=False,
        year=None,
        compression=None,
        geoparquet_version=None,
        mapping_file=None,
        original_geometries=False,
        **kwargs,
    ) -> str:
        columns = self.columns.copy()
        self.year = year
        """
        Converts an external datasets to Vecorel.
        """
        if self.bbox is not None and len(self.bbox) != 4:
            raise ValueError("If provided, the bounding box must consist of 4 numbers")

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
        request_args = {}
        if self.avoid_range_request:
            request_args["block_size"] = 0
        paths = self.download_files(urls, cache, **request_args)

        kwargs.update(self.open_options)
        gdf = self.read_data(paths, **kwargs)

        self.info("GeoDataFrame created from source(s):")
        # Make it so that everything is shown, don't output ... if there are too many columns or rows
        pd.set_option("display.max_columns", None)
        pd.set_option("display.max_rows", None)

        hash_before = self._hash_df(gdf.head())
        self.info(gdf.head())

        if self.index_as_id:
            gdf["id"] = gdf.index

        # 1. Run global migration
        self.info("Applying global migrations")
        gdf = self.migrate(gdf)
        assert isinstance(gdf, gpd.GeoDataFrame), "Migration function must return a GeoDataFrame"

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

        if hash_before != self._hash_df(gdf.head()):
            self.info("GeoDataFrame after migrations and filters:")
            self.info(gdf.head())

        # 5. Duplicate columns if needed
        actual_columns = {}
        for old_key, new_key in columns.items():
            if old_key in gdf.columns:
                # If the new keys are a list, duplicate the column
                if isinstance(new_key, list):
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

        gdf.sort_values("geometry", inplace=True, ignore_index=True)

        # 8. Remove all columns that are not listed
        drop_columns = list(set(gdf.columns) - set(actual_columns.values()))
        gdf.drop(columns=drop_columns, inplace=True)

        self.info("GeoDataFrame fully migrated:")
        self.info(gdf.head())

        collection = self.create_collection(gdf, source_coop_url=source_coop_url)

        self.info("Creating GeoParquet file: " + output_file)
        columns = list(actual_columns.values())
        pq = GeoParquet(output_file)
        pq.write(
            gdf,
            collection,
            properties=columns,
            missing_schemas=self.missing_schemas,
            compression=compression,
            geoparquet_version=geoparquet_version,
        )
        # if store_collection:
        #     external_collection = self._add_asset_to_collection(
        #         collection, output_file, rows=len(gdf), columns=pq_fields
        #     )
        #     collection_file = os.path.join(os.path.dirname(output_file), "collection.json")
        #     self.info("Creating Collection file: " + collection_file)
        #     with open(collection_file, "w") as f:
        #         json.dump(external_collection, f, indent=2)

        return output_file

    def __call__(self, *args, **kwargs):
        self.convert(*args, **kwargs)

    def _add_asset_to_collection(self, collection, output_file, rows=None, columns=None):
        c = collection.copy()
        if "assets" not in c or not isinstance(c["assets"], dict):
            c["assets"] = {}
        if "stac_extensions" not in c or not isinstance(c["stac_extensions"], list):
            c["stac_extensions"] = []

        c["stac_extensions"].append(STAC_TABLE_EXTENSION)

        table_columns = []
        for column in columns:
            table_columns.append({"name": column.name, "type": str(column.type)})

        asset = {
            "href": os.path.basename(output_file),
            "title": "Field Boundaries",
            "type": "application/vnd.apache.parquet",
            "roles": ["data"],
            "table:columns": table_columns,
            "table:primary_geometry": "geometry",
        }
        if rows is not None:
            asset["table:row_count"] = rows

        c["assets"]["data"] = asset

        return c

    def _hash_df(self, df):
        # dataframe is unhashable, this is a simple way to create a dafaframe-hash
        buf = StringIO()
        df.info(buf=buf)
        return hash(buf.getvalue())
