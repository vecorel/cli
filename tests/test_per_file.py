import io
import sys

import geopandas as gpd
import multivolumefile
import py7zr
import shapely
from loguru import logger

from vecorel_cli.conversion.base import BaseConverter
from vecorel_cli.conversion.per_file import PerFileConverterMixin


class Converter(PerFileConverterMixin, BaseConverter):
    id = "test"
    short_name = "Test"
    title = "Test dataset"
    description = "Test dataset"
    license = "CC0-1.0"
    variants = {"2024": None, "2025": None}
    columns = {"geometry": "geometry", "id": "id", "region": "region"}
    missing_schemas = {"properties": {"region": {"type": "string"}}}


def _source(folder, region):
    gdf = gpd.GeoDataFrame(
        {
            "id": [f"{region}-1", f"{region}-2"],
            "region": [region, region],
            "geometry": [shapely.box(0, 0, 1, 1), shapely.box(2, 0, 3, 1)],
        },
        crs="EPSG:4326",
    )
    path = folder / f"{region}.parquet"
    gdf.to_parquet(path)
    return path


def _capture_log():
    # loguru's default sink is bound to stderr at import, so point it at stdout
    logger.remove()
    logger.add(sys.stdout, format="{message}", level="DEBUG", colorize=False)


def test_each_source_is_converted_on_its_own_and_merged(tmp_path, capsys):
    sources = [_source(tmp_path, region) for region in ("a", "b")]
    output = tmp_path / "out" / "merged.parquet"
    _capture_log()

    Converter().convert(str(output), input_files={str(s): s.name for s in sources})

    merged = gpd.read_parquet(output)
    assert sorted(merged["id"]) == ["a-1", "a-2", "b-1", "b-2"]
    # constant within each part, so it only survives the merge as a column
    assert sorted(merged["region"].unique()) == ["a", "b"]
    assert [p.name for p in output.parent.iterdir()] == ["merged.parquet"]  # the parts are gone

    log = capsys.readouterr().out
    assert log.count("Using user provided input file(s)") == 1
    assert log.count("No variant given") == 1


def test_a_single_source_is_converted_directly(tmp_path):
    source = _source(tmp_path, "a")
    output = tmp_path / "single.parquet"

    Converter().convert(str(output), input_files={str(source): source.name})

    assert sorted(gpd.read_parquet(output)["id"]) == ["a-1", "a-2"]


def test_the_volumes_of_a_7z_archive_are_converted_together(tmp_path):
    archived = _source(tmp_path, "b")
    measure = io.BytesIO()
    with py7zr.SevenZipFile(measure, "w") as archive:
        archive.write(archived, archived.name)
    volume_size = len(measure.getvalue()) // 3 + 1
    with multivolumefile.MultiVolume(
        str(tmp_path / "b.7z"), mode="wb", volume=volume_size, ext_digits=3
    ) as volume:
        with py7zr.SevenZipFile(volume, "w") as archive:
            archive.write(archived, archived.name)
    volumes = sorted(tmp_path.glob("b.7z.*"))
    assert len(volumes) > 1, "the archive must span several volumes for this test"
    archived.unlink()

    source = _source(tmp_path, "a")
    output = tmp_path / "merged.parquet"
    # only the first volume names the target file
    input_files = {str(source): source.name}
    input_files |= {str(v): ([archived.name] if i == 0 else []) for i, v in enumerate(volumes)}

    Converter().convert(str(output), input_files=input_files)

    assert sorted(gpd.read_parquet(output)["id"]) == ["a-1", "a-2", "b-1", "b-2"]
