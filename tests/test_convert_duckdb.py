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
    # multi stays one multi-part feature, the bowtie is repaired into a valid
    # MultiPolygon, the point is dropped and the Z dimension is removed
    assert sorted(result["id"]) == ["bowtie", "multi", "square", "with_z"]
    types = dict(zip(result["id"], result.geometry.geom_type))
    assert types == {
        "square": "Polygon",
        "multi": "MultiPolygon",
        "bowtie": "MultiPolygon",
        "with_z": "Polygon",
    }
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


def test_duckdb_converter_numbers_rows_without_an_id_mapping(tmp_folder):
    src = _source_file(tmp_folder)
    dest = tmp_folder / "converted.parquet"

    columns = {"geometry": "geometry", "name": "name"}
    IndexConverter = type("IndexConverter", (DuckDBBaseConverter,), {**CONFIG, "columns": columns})
    IndexConverter().convert(dest, input_files={src: "source.parquet"})

    result = gpd.read_parquet(dest)
    # one row number per source feature; the point row is dropped afterwards
    assert sorted(result["id"]) == ["0", "1", "2", "3"]


def test_duckdb_converter_composes_id_from_id_columns(tmp_folder):
    """The composed id wins over the mapping to `id` in CONFIG, uses the migrated
    value of a part and accepts a constant from column_additions, like the
    GeoDataFrame-based codepath."""
    src = _source_file(tmp_folder)
    dest = tmp_folder / "converted.parquet"

    Composed = type(
        "ComposedConverter",
        (DuckDBBaseConverter,),
        {
            **CONFIG,  # keeps the '"id": "id"' mapping that id_columns must override
            "id_columns": ("campaign", "id", "name"),
            "id_separator": ":",
            "column_migrations": {"name": 'upper("name")'},
            # the float constant must format as 2026, not 2026.0
            "column_additions": {"campaign": 2026.0},
        },
    )
    Composed().convert(dest, input_files={src: "source.parquet"})

    result = gpd.read_parquet(dest)
    assert sorted(result["id"]) == [
        "2026:bowtie:C",
        "2026:multi:B",
        "2026:square:A",
        "2026:with_z:D",
    ]
    assert sorted(result["name"]) == ["A", "B", "C", "D"]


def test_duckdb_converter_migrated_float_id_parts_format_as_integers(tmp_folder):
    """A column migration that returns DOUBLE must not put '4.0' into the id;
    the GeoDataFrame-based codepath formats integer-valued floats as '4'."""
    gdf = gpd.GeoDataFrame(
        {
            "block": [7.0, 40.0],
            "name": ["a", "b"],
            "geometry": [shapely.box(0, 0, 1, 1), shapely.box(2, 0, 3, 1)],
        },
        crs="EPSG:4326",
    )
    src = tmp_folder / "floats.parquet"
    gdf.to_parquet(src)

    Composed = type(
        "MigratedFloatConverter",
        (DuckDBBaseConverter,),
        {
            **CONFIG,
            "columns": {"geometry": "geometry", "name": "name"},
            "id_columns": ("block", "name"),
            "id_separator": "_",
            "column_migrations": {"block": 'round("block")'},
        },
    )
    dest = tmp_folder / "converted.parquet"
    Composed().convert(dest, input_files={str(src): src.name})

    assert sorted(gpd.read_parquet(dest)["id"]) == ["40_b", "7_a"]


def test_boolean_id_parts_spell_the_same_in_both_codepaths(tmp_folder):
    """DuckDB renders a BOOLEAN as true/false, pandas as True/False; the same
    id_columns configuration must produce identical ids on both paths."""
    gdf = gpd.GeoDataFrame(
        {
            "flag": [True, False],
            "name": ["a", "b"],
            "geometry": [shapely.box(0, 0, 1, 1), shapely.box(2, 0, 3, 1)],
        },
        crs="EPSG:4326",
    )
    src = tmp_folder / "flags.parquet"
    gdf.to_parquet(src)

    config = {
        **CONFIG,
        "columns": {"geometry": "geometry", "name": "name"},
        "id_columns": ("flag", "name"),
        "id_separator": "_",
    }
    results = []
    for base in (DuckDBBaseConverter, BaseConverter):
        dest = tmp_folder / f"{base.__name__}.parquet"
        type("BoolConverter", (base,), dict(config))().convert(
            dest, input_files={str(src): src.name}
        )
        results.append(sorted(gpd.read_parquet(dest)["id"]))

    assert results[0] == results[1] == ["False_b", "True_a"]


def test_an_id_constant_loses_against_id_columns(tmp_folder):
    """A column_additions entry named `id` must not replace the composed id
    (in the DuckDB path the additions pass would strip that selection)."""
    gdf = gpd.GeoDataFrame(
        {
            "name": ["a", "b"],
            "geometry": [shapely.box(0, 0, 1, 1), shapely.box(2, 0, 3, 1)],
        },
        crs="EPSG:4326",
    )
    src = tmp_folder / "constant_id.parquet"
    gdf.to_parquet(src)

    config = {
        **CONFIG,
        "columns": {"geometry": "geometry", "name": "name"},
        "id_columns": ("name",),
        "column_additions": {"id": "constant"},
    }
    for base in (DuckDBBaseConverter, BaseConverter):
        dest = tmp_folder / f"{base.__name__}.parquet"
        type("ConstantIdConverter", (base,), dict(config))().convert(
            dest, input_files={str(src): src.name}
        )
        assert sorted(gpd.read_parquet(dest)["id"]) == ["a", "b"], base.__name__


def test_duckdb_converter_rejects_a_null_constant_id_part(tmp_folder):
    """str(None) would bake the literal "None" into every id; fail like the
    GeoDataFrame-based codepath, which fails on the null ids."""
    gdf = gpd.GeoDataFrame(
        {"name": ["a"], "geometry": [shapely.box(0, 0, 1, 1)]}, crs="EPSG:4326"
    )
    src = tmp_folder / "null_constant.parquet"
    gdf.to_parquet(src)

    Composed = type(
        "NullConstantConverter",
        (DuckDBBaseConverter,),
        {
            **CONFIG,
            "columns": {"geometry": "geometry", "name": "name"},
            "id_columns": ("campaign", "name"),
            "column_additions": {"campaign": None},
        },
    )
    with pytest.raises(ValueError, match="null constant"):
        Composed().convert(tmp_folder / "converted.parquet", input_files={str(src): src.name})


def test_duckdb_converter_rejects_a_migrated_constant_id_part(tmp_folder):
    """A migration expression references a column that a constant never becomes
    in this codepath; fail loudly instead of diverging from the GeoDataFrame
    path, which migrates the added column."""
    gdf = gpd.GeoDataFrame(
        {"name": ["a"], "geometry": [shapely.box(0, 0, 1, 1)]}, crs="EPSG:4326"
    )
    src = tmp_folder / "constant.parquet"
    gdf.to_parquet(src)

    Composed = type(
        "MigratedConstantConverter",
        (DuckDBBaseConverter,),
        {
            **CONFIG,
            "columns": {"geometry": "geometry", "name": "name"},
            "id_columns": ("campaign", "name"),
            "column_additions": {"campaign": "2026"},
            "column_migrations": {"campaign": 'upper("campaign")'},
        },
    )
    with pytest.raises(ValueError, match="cannot compose"):
        Composed().convert(tmp_folder / "converted.parquet", input_files={str(src): src.name})


def test_duckdb_converter_rejects_decimal_id_parts(tmp_folder):
    """A float id part with true decimals must fail instead of being rounded
    into an id that can collide with a genuine integer id."""
    gdf = gpd.GeoDataFrame(
        {
            "block": [4.5, 5.0],
            "name": ["a", "b"],
            "geometry": [shapely.box(0, 0, 1, 1), shapely.box(2, 0, 3, 1)],
        },
        crs="EPSG:4326",
    )
    src = tmp_folder / "decimals.parquet"
    gdf.to_parquet(src)

    Composed = type(
        "DecimalConverter",
        (DuckDBBaseConverter,),
        {
            **CONFIG,
            "columns": {"geometry": "geometry", "name": "name"},
            "id_columns": ("block",),
        },
    )
    with pytest.raises(Exception, match="decimal values"):
        Composed().convert(tmp_folder / "converted.parquet", input_files={str(src): src.name})


def test_duckdb_converter_numbered_ids_avoid_existing_ids(tmp_folder):
    """A numbered id must not collide with an id the source already carries:
    x, x, x~1 must not end as x~1 twice."""
    gdf = gpd.GeoDataFrame(
        {
            "id": ["x", "x", "x~1"],
            "name": ["a", "b", "c"],
            "geometry": [shapely.box(n, 0, n + 1, 1) for n in range(3)],
        },
        crs="EPSG:4326",
    )
    src = tmp_folder / "collisions.parquet"
    gdf.to_parquet(src)
    dest = tmp_folder / "converted.parquet"

    Converter().convert(dest, input_files={str(src): src.name})

    ids = gpd.read_parquet(dest)["id"]
    assert ids.is_unique, ids.tolist()
    assert len(ids) == 3


def test_duckdb_converter_extracts_polygons_from_collections(tmp_folder):
    """make_valid() can emit a GeometryCollection of polygons plus line/point
    debris; only the polygonal parts may survive, and a feature without any
    is dropped (like the GeoDataFrame-based codepath)."""
    gdf = gpd.GeoDataFrame(
        {
            "id": ["collection", "debris", "overlap", "nested"],
            "name": ["a", "b", "c", "d"],
            "geometry": [
                shapely.GeometryCollection(
                    [
                        shapely.Polygon([(0, 0), (0, 1), (1, 1), (1, 0)]),
                        shapely.LineString([(0, 2), (1, 2)]),
                    ]
                ),
                shapely.GeometryCollection([shapely.LineString([(2, 2), (3, 2)])]),
                # members of a collection may overlap; the row must survive as a
                # valid geometry instead of becoming an invalid MultiPolygon
                shapely.GeometryCollection([shapely.box(4, 0, 6, 2), shapely.box(5, 1, 7, 3)]),
                shapely.GeometryCollection(
                    [
                        shapely.GeometryCollection([shapely.box(8, 0, 9, 1)]),
                        shapely.LineString([(8, 2), (9, 2)]),
                    ]
                ),
            ],
        },
        crs="EPSG:4326",
    )
    src = tmp_folder / "collections.parquet"
    gdf.to_parquet(src)
    dest = tmp_folder / "converted.parquet"

    Converter().convert(dest, input_files={str(src): src.name})

    result = gpd.read_parquet(dest)
    assert sorted(result["id"]) == ["collection", "nested", "overlap"]
    assert result.geometry.is_valid.all()
    assert set(result.geometry.geom_type) <= {"Polygon", "MultiPolygon"}


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
    assert len(gpd.read_parquet(dest)) == 8

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
    dest = tmp_folder / "dup_merged.parquet"
    Converter().merge_parquet(parts, dest)
    assert "'id' is not unique" in capsys.readouterr().out
    # the repeats are numbered, so the merged file is still valid
    ids = gpd.read_parquet(dest)["id"]
    assert ids.is_unique
    assert sorted(ids[ids.str.startswith("same")]) == ["same~1", "same~2"]


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


def test_merge_parquet_refuses_parts_in_different_crs(tmp_folder):
    parts = []
    for index, crs in enumerate(("EPSG:4326", "EPSG:3857")):
        gdf = gpd.GeoDataFrame(
            {"id": [f"{index}"], "name": ["a"], "geometry": [shapely.box(0, 0, 1, 1)]},
            crs="EPSG:4326",
        ).to_crs(crs)
        src = tmp_folder / f"crs_src_{index}.parquet"
        gdf.to_parquet(src)
        part = tmp_folder / f"crs_part_{index}.parquet"
        Converter().convert(part, input_files={str(src): src.name})
        parts.append(part)

    with pytest.raises(ValueError, match="different coordinate reference systems"):
        Converter().merge_parquet(parts, tmp_folder / "merged.parquet")


def test_merge_parquet_unions_parts_that_differ(tmp_folder):
    """A converter drops a column a source file does not have, so two parts of one
    dataset can differ; the merge must not fail on that."""
    parts = []
    for index, columns in enumerate(({"id": ["0"], "name": ["a"]}, {"id": ["1"]})):
        gdf = gpd.GeoDataFrame(
            {**columns, "geometry": [shapely.box(index, 0, index + 1, 1)]}, crs="EPSG:4326"
        )
        src = tmp_folder / f"u_src_{index}.parquet"
        gdf.to_parquet(src)
        part = tmp_folder / f"u_part_{index}.parquet"
        Converter().convert(part, input_files={str(src): src.name})
        parts.append(part)

    dest = tmp_folder / "unioned.parquet"
    Converter().merge_parquet(parts, dest)
    table = pq.read_table(dest)
    assert table.num_rows == 2
    assert "name" in table.schema.names
    assert sorted(x for x in table.column("id").to_pylist()) == ["0", "1"]


def test_merge_parquet_checks_ids_that_convert_generated(tmp_folder, capsys):
    """Each part numbered its own rows from zero, so the merge has to check what
    convert() is allowed to take for granted."""
    IndexConverter = type(
        "IndexConverter",
        (DuckDBBaseConverter,),
        {**CONFIG, "columns": {"geometry": "geometry", "name": "name"}},
    )
    parts = []
    for index in range(2):
        gdf = gpd.GeoDataFrame(
            {
                "name": ["a", "b"],
                "geometry": [
                    shapely.box(index, 0, index + 1, 1),
                    shapely.box(index, 2, index + 1, 3),
                ],
            },
            crs="EPSG:4326",
        )
        src = tmp_folder / f"idx_src_{index}.parquet"
        gdf.to_parquet(src)
        part = tmp_folder / f"idx_part_{index}.parquet"
        IndexConverter().convert(part, input_files={str(src): src.name})
        parts.append(part)

    # both parts start at 0, so every id occurs twice
    assert (
        pq.read_table(parts[0]).column("id").to_pylist()
        == pq.read_table(parts[1]).column("id").to_pylist()
    )

    logger.remove()
    logger.add(sys.stdout, format="{message}", level="DEBUG", colorize=False)
    dest = tmp_folder / "idx_merged.parquet"
    IndexConverter().merge_parquet(parts, dest)
    assert "'id' is not unique" in capsys.readouterr().out
    assert gpd.read_parquet(dest)["id"].is_unique


def _null_id_source(folder):
    gdf = gpd.GeoDataFrame(
        {
            "id": ["a", None, "b"],
            "name": ["a", "b", "c"],
            "geometry": [shapely.box(n, 0, n + 1, 1) for n in range(3)],
        },
        crs="EPSG:4326",
    )
    path = folder / "null_id.parquet"
    gdf.to_parquet(path)
    return str(path)


@pytest.mark.parametrize("cls", [Converter, PandasConverter], ids=["duckdb", "pandas"])
def test_required_null_is_an_error(tmp_folder, cls):
    """A null in a schema-required property fails the conversion, whatever the
    count; silently dropping rows would make that data-quality decision for
    the user (vecorel/cli#33)."""
    src = _null_id_source(tmp_folder)
    with pytest.raises(ValueError, match="required property"):
        cls().convert(tmp_folder / "converted.parquet", input_files={src: "source.parquet"})


def test_required_null_excluded_with_column_filters(tmp_folder):
    """The converter handles incomplete rows explicitly, e.g. with a filter."""
    src = _null_id_source(tmp_folder)

    FilteredDuck = type(
        "FilteredDuck",
        (DuckDBBaseConverter,),
        {**CONFIG, "column_filters": {"id": '"id" IS NOT NULL'}},
    )
    dest = tmp_folder / "duck.parquet"
    FilteredDuck().convert(dest, input_files={src: "source.parquet"})
    assert sorted(gpd.read_parquet(dest)["id"]) == ["a", "b"]

    FilteredPandas = type(
        "FilteredPandas",
        (BaseConverter,),
        {**CONFIG, "column_filters": {"id": lambda col: col.notna()}},
    )
    dest = tmp_folder / "pandas.parquet"
    FilteredPandas().convert(dest, input_files={src: "source.parquet"})
    assert sorted(gpd.read_parquet(dest)["id"]) == ["a", "b"]


@pytest.mark.parametrize("cls", [Converter, PandasConverter], ids=["duckdb", "pandas"])
def test_blank_geometry_is_dropped_and_reported(tmp_folder, cls, capsys):
    gdf = gpd.GeoDataFrame(
        {
            "id": ["a", "b"],
            "name": ["a", "b"],
            "geometry": [shapely.box(0, 0, 1, 1), None],
        },
        crs="EPSG:4326",
    )
    src = tmp_folder / "blank.parquet"
    gdf.to_parquet(src)

    logger.remove()
    logger.add(sys.stdout, format="{message}", level="DEBUG", colorize=False)
    dest = tmp_folder / "converted.parquet"
    cls().convert(dest, input_files={str(src): "blank.parquet"})

    assert "Dropping 1 of 2 rows with an empty or missing geometry" in capsys.readouterr().out
    assert gpd.read_parquet(dest)["id"].to_list() == ["a"]


@pytest.mark.parametrize("cls", [Converter, PandasConverter], ids=["duckdb", "pandas"])
def test_rows_without_a_polygonal_geometry_are_reported(tmp_folder, cls, capsys):
    """The polygonal filter after geometry repair must say what it removed."""
    src = _source_file(tmp_folder)
    logger.remove()
    logger.add(sys.stdout, format="{message}", level="DEBUG", colorize=False)
    cls().convert(tmp_folder / "converted.parquet", input_files={src: "source.parquet"})
    # the point row has nothing polygonal to keep
    out = capsys.readouterr().out
    assert "Dropping 1 of 5 rows without a polygonal geometry" in out, out


def test_merge_parquet_keeps_a_crs_duckdb_would_drop(tmp_folder):
    """DuckDB before 1.5 writes no CRS into the merged file's metadata, so it has to
    come from the parts. Checked with a CRS that is not the default."""
    parts = []
    for index in range(2):
        gdf = gpd.GeoDataFrame(
            {"id": [f"{index}"], "name": ["a"], "geometry": [shapely.box(index, 0, index + 1, 1)]},
            crs="EPSG:4326",
        ).to_crs("EPSG:3857")
        src = tmp_folder / f"crs_keep_src_{index}.parquet"
        gdf.to_parquet(src)
        part = tmp_folder / f"crs_keep_part_{index}.parquet"
        Converter().convert(part, input_files={str(src): src.name})
        parts.append(part)

    dest = tmp_folder / "crs_keep.parquet"
    Converter().merge_parquet(parts, dest)

    geo = json.loads(pq.read_table(dest).schema.metadata[b"geo"])
    crs = geo["columns"][geo["primary_column"]]["crs"]
    assert crs is not None, "the merged file lost the CRS of its parts"
    assert "3857" in json.dumps(crs)
