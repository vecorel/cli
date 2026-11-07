import io
import sys
import zipfile

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


def _write_multivolume_7z(path, file):
    measure = io.BytesIO()
    with py7zr.SevenZipFile(measure, "w") as archive:
        archive.write(file, file.name)
    volume_size = len(measure.getvalue()) // 3 + 1
    with multivolumefile.MultiVolume(
        str(path), mode="wb", volume=volume_size, ext_digits=3
    ) as volume:
        with py7zr.SevenZipFile(volume, "w") as archive:
            archive.write(file, file.name)
    volumes = sorted(path.parent.glob(path.name + ".*"))
    assert len(volumes) > 1, "the archive must span several volumes for this test"
    return volumes


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


class SideFileConverter(Converter):
    side_files = ("names.csv",)
    columns = {**Converter.columns, "name": "name"}
    missing_schemas = {"properties": {"region": {"type": "string"}, "name": {"type": "string"}}}

    def migrate(self, gdf):
        return gdf.merge(self.read_side_file("names.csv"), on="region", how="left")


def test_side_files_go_with_every_part(tmp_path):
    sources = [_source(tmp_path, region) for region in ("a", "b")]
    (tmp_path / "names.csv").write_text("region,name\na,Alpha\nb,Beta\n")

    output = tmp_path / "merged.parquet"
    input_files = {str(s): s.name for s in sources} | {str(tmp_path / "names.csv"): "names.csv"}
    SideFileConverter().convert(str(output), input_files=input_files)

    merged = gpd.read_parquet(output).sort_values("id")
    assert merged["name"].tolist() == ["Alpha", "Alpha", "Beta", "Beta"]


def test_side_files_in_an_archive_with_geodata_go_with_every_part(tmp_path):
    archived = _source(tmp_path, "a")
    (tmp_path / "names.csv").write_text("region,name\na,Alpha\nb,Beta\n")
    with zipfile.ZipFile(tmp_path / "a.zip", "w") as archive:
        archive.write(archived, archived.name)
        archive.write(tmp_path / "names.csv", "names.csv")
    source = _source(tmp_path, "b")

    output = tmp_path / "merged.parquet"
    input_files = {str(tmp_path / "a.zip"): [archived.name, "names.csv"], str(source): source.name}
    SideFileConverter().convert(str(output), input_files=input_files)

    merged = gpd.read_parquet(output).sort_values("id")
    assert merged["id"].tolist() == ["a-1", "a-2", "b-1", "b-2"]
    assert merged["name"].tolist() == ["Alpha", "Alpha", "Beta", "Beta"]


def test_side_files_in_a_multivolume_7z_archive_go_with_every_part(tmp_path):
    sources = [_source(tmp_path, region) for region in ("a", "b")]
    names = tmp_path / "names.csv"
    names.write_text("region,name\na,Alpha\nb,Beta\n")
    volumes = _write_multivolume_7z(tmp_path / "names.7z", names)
    names.unlink()

    output = tmp_path / "merged.parquet"
    input_files = {str(s): s.name for s in sources}
    input_files |= {str(v): (["names.csv"] if i == 0 else []) for i, v in enumerate(volumes)}
    SideFileConverter().convert(str(output), input_files=input_files)

    merged = gpd.read_parquet(output).sort_values("id")
    assert merged["id"].tolist() == ["a-1", "a-2", "b-1", "b-2"]
    assert merged["name"].tolist() == ["Alpha", "Alpha", "Beta", "Beta"]


def test_a_single_source_is_converted_directly(tmp_path):
    source = _source(tmp_path, "a")
    output = tmp_path / "single.parquet"

    Converter().convert(str(output), input_files={str(source): source.name})

    assert sorted(gpd.read_parquet(output)["id"]) == ["a-1", "a-2"]


def test_the_volumes_of_a_7z_archive_are_converted_together(tmp_path):
    archived = _source(tmp_path, "b")
    volumes = _write_multivolume_7z(tmp_path / "b.7z", archived)
    archived.unlink()

    source = _source(tmp_path, "a")
    output = tmp_path / "merged.parquet"
    # only the first volume names the target file
    input_files = {str(source): source.name}
    input_files |= {str(v): ([archived.name] if i == 0 else []) for i, v in enumerate(volumes)}

    Converter().convert(str(output), input_files=input_files)

    assert sorted(gpd.read_parquet(output)["id"]) == ["a-1", "a-2", "b-1", "b-2"]
