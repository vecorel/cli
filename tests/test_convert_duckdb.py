import json
import sys

import geopandas as gpd
import numpy as np
import pyarrow.parquet as pq
import pytest
import shapely
from loguru import logger

from vecorel_cli.conversion.base import BaseConverter
from vecorel_cli.conversion.duckdb import DuckDBBaseConverter
from vecorel_cli.validate import ValidateData
from vecorel_cli.vecorel.hilbert import hilbert_keys_for_table

# One shared converter configuration, so the two codepaths cannot drift apart.
# column_filters and column_migrations must stay out of it: they are Python
# callables in the GeoDataFrame-based codepath and SQL fragments in the
# DuckDB-based one.
CONFIG = {
    "id": "test",
    "short_name": "Test",
    "title": "Test dataset",
    "description": "Test dataset",
    "license": "CC0-1.0",
    "columns": {
        "geometry": "geometry",
        "id": "id",
        "name": "name",
    },
    "missing_schemas": {
        "properties": {
            "name": {"type": "string"},
        }
    },
}

Converter = type("Converter", (DuckDBBaseConverter,), dict(CONFIG))
PandasConverter = type("PandasConverter", (BaseConverter,), dict(CONFIG))


def _source_file(folder):
    """A source with everything the geometry handling must fix:
    a multi-part geometry, an invalid bowtie, a Z polygon, and a point."""
    square = shapely.Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])
    multi = shapely.MultiPolygon(
        [
            shapely.Polygon([(2, 0), (2, 1), (3, 1), (3, 0)]),
            shapely.Polygon([(4, 0), (4, 1), (5, 1), (5, 0)]),
        ]
    )
    bowtie = shapely.Polygon([(6, 0), (7, 1), (7, 0), (6, 1)])
    with_z = shapely.Polygon([(8, 0, 5), (8, 1, 5), (9, 1, 5), (9, 0, 5)])
    point = shapely.Point(10, 0)

    gdf = gpd.GeoDataFrame(
        {
            "id": ["square", "multi", "bowtie", "with_z", "point"],
            "name": ["a", "b", "c", "d", "e"],
            "geometry": [square, multi, bowtie, with_z, point],
        },
        crs="EPSG:4326",
    )
    path = folder / "source.parquet"
    gdf.to_parquet(path)
    return str(path)


def test_duckdb_converter(tmp_folder):
    src = _source_file(tmp_folder)
    dest = tmp_folder / "converted.parquet"

    Converter().convert(dest, input_files={src: "source.parquet"})

    result = gpd.read_parquet(dest)
    # multi is split in two, bowtie is repaired into two valid polygons,
    # the point is dropped and the Z dimension is removed
    assert sorted(result["id"]) == ["bowtie", "bowtie", "multi", "multi", "square", "with_z"]
    assert set(result.geometry.geom_type) == {"Polygon"}
    assert result.geometry.is_valid.all()
    assert not result.geometry.has_z.any()

    with pq.ParquetFile(dest) as pf:
        schema = pf.schema_arrow
    field = schema.field("geometry")
    assert str(field.type) == "binary"
    assert not field.nullable
    field = schema.field("id")
    assert str(field.type) == "string"
    assert not field.nullable
    assert str(schema.field("name").type) == "string"
    assert "bbox" in schema.names

    # sorted against the CRS-derived Hilbert grid
    with pq.ParquetFile(dest) as pf:
        table = pf.read()
    keys = hilbert_keys_for_table(table, "geometry", (-180.0, -90.0, 180.0, 90.0))
    assert bool(np.all(keys[1:] >= keys[:-1]))

    validation = ValidateData().validate(dest, num=100, schema_map={})
    assert validation.errors == []


def test_duckdb_converter_index_as_id(tmp_folder):
    src = _source_file(tmp_folder)
    dest = tmp_folder / "converted.parquet"

    IndexConverter = type("IndexConverter", (DuckDBBaseConverter,), {**CONFIG, "index_as_id": True})
    IndexConverter().convert(dest, input_files={src: "source.parquet"})

    result = gpd.read_parquet(dest)
    # row numbers are assigned before geometries are split,
    # so the parts of one source feature share an id (like the default codepath)
    assert sorted(result["id"]) == ["0", "1", "1", "2", "2", "3"]


def test_duckdb_converter_source_crs(tmp_folder):
    src1 = _source_file(tmp_folder)
    dest = tmp_folder / "converted.parquet"

    # the same CRS, declared as a differently rendered PROJJSON object
    table = pq.read_table(src1)
    metadata = dict(table.schema.metadata)
    geo = json.loads(metadata[b"geo"])
    crs = geo["columns"]["geometry"]["crs"]
    crs.pop("scope", None)
    crs.pop("area", None)
    crs["$schema"] = "https://proj.org/schemas/v0.5/projjson.schema.json"
    metadata[b"geo"] = json.dumps(geo).encode()
    src2 = str(tmp_folder / "source2.parquet")
    pq.write_table(table.replace_schema_metadata(metadata), src2)

    Converter().convert(dest, input_files={src1: "a.parquet", src2: "b.parquet"})
    assert len(gpd.read_parquet(dest)) == 12

    src3 = str(tmp_folder / "source3.parquet")
    gpd.read_parquet(src1).to_crs("EPSG:3857").to_parquet(src3)
    with pytest.raises(ValueError, match="different coordinate reference"):
        Converter().convert(dest, input_files={src1: "a.parquet", src3: "c.parquet"})


def test_duckdb_converter_original_geometries(tmp_folder):
    src = _source_file(tmp_folder)
    dest = tmp_folder / "converted.parquet"

    Converter().convert(dest, input_files={src: "source.parquet"}, original_geometries=True)

    result = gpd.read_parquet(dest)
    assert len(result) == 5
    assert set(result.geometry.geom_type) == {"Polygon", "MultiPolygon", "Point"}


def test_codepath_parity(tmp_folder):
    """The GeoDataFrame-based and the DuckDB-based codepaths must produce
    comparable files from the same source and converter configuration:
    same schema, same rows in the same order, same key metadata, same packaging.
    """
    src = _source_file(tmp_folder)
    kwargs = {
        "input_files": {src: "source.parquet"},
        "compression": "zstd",
        "geoparquet_version": "1.1.0",
    }
    pandas_dest = tmp_folder / "pandas.parquet"
    duckdb_dest = tmp_folder / "duckdb.parquet"
    PandasConverter().convert(pandas_dest, **kwargs)
    Converter().convert(duckdb_dest, **kwargs)

    with pq.ParquetFile(pandas_dest) as pf:
        pandas_schema = pf.schema_arrow
        pandas_table = pf.read()
        pandas_groups = pf.metadata.num_row_groups
        pandas_compression = pf.metadata.row_group(0).column(0).compression
    with pq.ParquetFile(duckdb_dest) as pf:
        duckdb_schema = pf.schema_arrow
        duckdb_table = pf.read()
        duckdb_groups = pf.metadata.num_row_groups
        duckdb_compression = pf.metadata.row_group(0).column(0).compression

    # Same columns with the same types and nullability (the column order is
    # allowed to differ)
    assert sorted(pandas_schema.names) == sorted(duckdb_schema.names)
    for name in pandas_schema.names:
        f1, f2 = pandas_schema.field(name), duckdb_schema.field(name)
        assert f1.type == f2.type, f"{name}: {f1.type} != {f2.type}"
        assert f1.nullable == f2.nullable, f"{name}: nullability differs"

    # Same rows in the same (Hilbert) order; the geometries must describe the
    # same shapes, but the WKB may differ in vertex order (different GEOS builds)
    assert pandas_table.num_rows == duckdb_table.num_rows
    assert pandas_table["id"].to_pylist() == duckdb_table["id"].to_pylist()
    assert pandas_table["name"].to_pylist() == duckdb_table["name"].to_pylist()
    pandas_geoms = shapely.from_wkb(pandas_table["geometry"].to_pylist())
    duckdb_geoms = shapely.from_wkb(duckdb_table["geometry"].to_pylist())
    for g1, g2 in zip(pandas_geoms, duckdb_geoms):
        assert shapely.equals(g1, g2), f"{shapely.to_wkt(g1)} != {shapely.to_wkt(g2)}"

    # Same collection metadata and the same key GeoParquet metadata
    pandas_collection = json.loads(pandas_schema.metadata[b"collection"])
    duckdb_collection = json.loads(duckdb_schema.metadata[b"collection"])
    assert pandas_collection == duckdb_collection

    pandas_geo = json.loads(pandas_schema.metadata[b"geo"])
    duckdb_geo = json.loads(duckdb_schema.metadata[b"geo"])
    for key in ("version", "primary_column"):
        assert pandas_geo[key] == duckdb_geo[key]
    pandas_column = pandas_geo["columns"]["geometry"]
    duckdb_column = duckdb_geo["columns"]["geometry"]
    for key in ("encoding", "covering", "crs", "bbox"):
        assert pandas_column.get(key) == duckdb_column.get(key), f"geo {key} differs"
    assert sorted(pandas_column.get("geometry_types", [])) == sorted(
        duckdb_column.get("geometry_types", [])
    )

    # Same packaging
    assert pandas_compression == duckdb_compression
    assert pandas_groups == duckdb_groups

    # Both validate
    for dest in (pandas_dest, duckdb_dest):
        validation = ValidateData().validate(dest, num=100, schema_map={})
        assert validation.errors == []


def test_merge_parquet(tmp_folder):
    """Converted files combine into one, sorted over the whole set and
    packaged like any other output."""
    parts = []
    for index, offset in enumerate((0, 20)):
        gdf = gpd.GeoDataFrame(
            {
                "id": [f"{index}-{n}" for n in range(3)],
                "name": ["a", "b", "c"],
                "geometry": [shapely.box(offset + n, 0, offset + n + 1, 1) for n in range(3)],
            },
            crs="EPSG:4326",
        )
        src = tmp_folder / f"src_{index}.parquet"
        gdf.to_parquet(src)
        part = tmp_folder / f"part_{index}.parquet"
        Converter().convert(part, input_files={str(src): src.name})
        parts.append(part)

    dest = tmp_folder / "merged.parquet"
    Converter().merge_parquet(parts, dest)

    result = gpd.read_parquet(dest)
    assert sorted(result["id"]) == ["0-0", "0-1", "0-2", "1-0", "1-1", "1-2"]

    with pq.ParquetFile(dest) as pf:
        table = pf.read()
    # sorted over the merged set, not per part
    keys = hilbert_keys_for_table(table, "geometry", (-180.0, -90.0, 180.0, 90.0))
    assert bool(np.all(keys[1:] >= keys[:-1]))
    assert "bbox" in table.schema.names
    assert b"collection" in table.schema.metadata

    assert ValidateData().validate(dest, num=100, schema_map={}).errors == []


def test_merge_parquet_sees_an_id_that_repeats_across_parts(tmp_folder, capsys):
    """A per-part check cannot see this; a check over the merge can."""
    parts = []
    for index in range(2):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["same", f"other-{index}"],
                "name": ["a", "b"],
                "geometry": [
                    shapely.box(index, 0, index + 1, 1),
                    shapely.box(index, 2, index + 1, 3),
                ],
            },
            crs="EPSG:4326",
        )
        src = tmp_folder / f"dup_src_{index}.parquet"
        gdf.to_parquet(src)
        part = tmp_folder / f"dup_part_{index}.parquet"
        Converter().convert(part, input_files={str(src): src.name})
        parts.append(part)

    # loguru's default sink is bound to stderr at import, so point it at stdout
    logger.remove()
    logger.add(sys.stdout, format="{message}", level="DEBUG", colorize=False)
    Converter().merge_parquet(parts, tmp_folder / "dup_merged.parquet")
    assert "'id' is not unique" in capsys.readouterr().out


def test_merge_parquet_rejects_empty_input(tmp_folder):
    with pytest.raises(ValueError, match="No paths"):
        Converter().merge_parquet([], tmp_folder / "nothing.parquet")


def test_duckdb_converter_can_keep_the_constants_in_columns(tmp_folder):
    """A conversion that writes one part of a dataset cannot let constants move
    into the collection metadata, in this codepath either."""
    src = _source_file(tmp_folder)
    dest = tmp_folder / "hydrated.parquet"

    Hydrated = type(
        "Hydrated",
        (DuckDBBaseConverter,),
        {
            **CONFIG,
            "dehydrate": False,
            "column_additions": {"region": "north"},
            "missing_schemas": {
                "properties": {"name": {"type": "string"}, "region": {"type": "string"}}
            },
        },
    )
    Hydrated().convert(dest, input_files={src: "source.parquet"})

    table = pq.read_table(dest)
    assert "region" in table.schema.names, "the constant should have stayed a column"
    assert set(table.column("region").to_pylist()) == {"north"}
    assert "region" not in json.loads(table.schema.metadata[b"collection"])
