import os
import sys
import time

import click
import pandas as pd

from .const import (
    COMPRESSION_METHODS,
    CORE_COLUMNS,
    VECOREL_GEOJSON_DATATYPES_SCHEMA,
    VECOREL_SPECIFICAION_SCHEMA,
)
from .convert import convert as convert_
from .convert import list_all_converter_ids, list_all_converters
from .create_geojson import create_geojson as create_geojson_
from .create_geoparquet import create_geoparquet as create_geoparquet_
from .create_jsonschema import CreateJsonSchema
from .describe import describe as describe_
from .improve import ImproveData
from .merge import DEFAULT_CRS
from .merge import merge as merge_
from .rename_extension import RenameExtension
from .util import (
    check_ext_schema_for_cli,
    log,
    parse_converter_input_files,
    parse_map,
    valid_file_for_cli,
    valid_file_for_cli_with_ext,
    valid_files_folders_for_cli,
    valid_folder_for_cli,
)
from .validate import validate as validate_
from .validate_schema import ValidateSchema
from .version import __version__
from .version import vecorel_version as vecorel_version_

# todo: https://stackoverflow.com/questions/50061342/is-it-possible-to-reuse-python-click-option-decorators-for-multiple-commands


@click.group()
@click.version_option(version=__version__)
def cli():
    """
    The Vecorel CLI.
    """
    pass


## DESCRIBE
@click.command()
@click.argument(
    "file",
    nargs=1,
    callback=lambda ctx, param, value: valid_file_for_cli_with_ext(
        value, ["parquet", "geoparquet"]
    ),
)
@click.option(
    "--json", "-j", is_flag=True, type=click.BOOL, help="Print the JSON metadata.", default=False
)
@click.option(
    "--num",
    "-n",
    type=click.IntRange(min=0),
    help="Number of rows to show.",
    show_default=True,
    default=10,
)
@click.option(
    "--column",
    "-c",
    type=click.STRING,
    multiple=True,
    help="Column names to show in the excerpt. Can be used multiple times. Shows all by default.",
    default=[],
)
def describe(file, json, num=10, column=[]):
    """
    Inspects the content of a Vecorel GeoParquet file.
    """
    log(f"Vecorel CLI {__version__} - Describe {file}\n", "success")
    try:
        if len(column) == 0:
            columns = None
        else:
            columns = list(column)
        describe_(file, json, num, columns)
    except Exception as e:
        log(e, "error")
        sys.exit(1)


## VALIDATE
@click.command()
@click.argument(
    "files",
    nargs=-1,
    callback=lambda ctx, param, value: valid_files_folders_for_cli(
        value, ["parquet", "geoparquet", "json", "geojson"]
    ),
)
@click.option(
    "--data",
    "-d",
    is_flag=True,
    type=click.BOOL,
    help="EXPERIMENTAL: Validate the data in the GeoParquet file. Enabling this might be slow or exceed memory. Default is False.",
    default=False,
)
@click.option(
    "--schemas",
    "-s",
    multiple=True,
    callback=lambda ctx, param, value: check_ext_schema_for_cli(value, allow_none=False),
    help="Maps a remote Vecorel schema URL to a local file. First the URL, then the local file path. Separated with a comma character. Example: https://example.com/schema.yaml,/path/to/schema.yaml",
)
@click.option(
    "--timer",
    is_flag=True,
    type=click.BOOL,
    help="Measure the time the validation took.",
    default=False,
    hidden=True,
)
def validate(files, data, schemas, timer):
    """
    Validates a Vecorel GeoParquet or GeoJSON file.
    """
    start = time.perf_counter()
    log(f"Vecorel CLI {__version__} - Validator\n", "success")
    config = {
        "schemas": schemas,
        "data": data,
    }

    if len(files) == 0:
        log("No files to validate", "error")
        sys.exit(1)

    exit = 0
    for file in files:
        log(f"Validating {file}", "info")
        try:
            start_step = time.perf_counter()
            result = validate_(file, config)
            if result:
                log("\n  => VALID\n", "success")
            else:
                log("\n  => INVALID\n", "error")
                exit = 1
        except Exception as e:
            log(f"\n  => UNKNOWN: {e}\n", "error")
            exit = 2
        finally:
            if timer:
                end_step = time.perf_counter()
                log(f"Validated {file} in {end_step - start_step:0.4f} seconds")

    if timer:
        end = time.perf_counter()
        log(f"All validated in {end - start:0.4f} seconds")

    sys.exit(exit)


## VALIDATE SCHEMA
@click.command()
@click.argument(
    "files",
    nargs=-1,
    callback=lambda ctx, param, value: valid_files_folders_for_cli(value, ["yaml", "yml"]),
)
@click.option(
    "--metaschema",
    "-m",
    callback=valid_file_for_cli,
    help="Vecorel SDL metaschema to validate against.",
    default=None,
)
def validate_schema(files, metaschema):
    """
    Validates a Vecorel schema file.
    """
    ValidateSchema(metaschema).run(files)


## CREATE PARQUET
@click.command()
@click.argument(
    "files",
    nargs=-1,
    callback=lambda ctx, param, value: valid_files_folders_for_cli(value, ["json", "geojson"]),
)
@click.option(
    "--out", "-o", type=click.Path(exists=False), help="Path to write the file to.", required=True
)
@click.option(
    "--schemas",
    "-s",
    multiple=True,
    callback=lambda ctx, param, value: check_ext_schema_for_cli(value, allow_none=False),
    help="Maps a remote Vecorel schema URL to a local file. First the URL, then the local file path. Separated with a comma character. Example: https://example.com/schema.yaml,/path/to/schema.yaml",
)
def create_geoparquet(files, out, schemas):
    """
    Create a Vecorel GeoParquet file from Vecorel GeoJSON file(s).
    """
    log(f"Vecorel CLI {__version__} - Create GeoParquet\n", "success")
    config = {
        "files": files,
        "out": out,
        "schemas": schemas,
    }
    try:
        create_geoparquet_(config)
    except Exception as e:
        log(e, "error")
        sys.exit(1)


## CREATE GEOJSON
@click.command()
@click.argument(
    "file",
    nargs=1,
    callback=lambda ctx, param, value: valid_file_for_cli_with_ext(
        value, ["parquet", "geoparquet"]
    ),
)
@click.option(
    "--out",
    "-o",
    type=click.Path(exists=False),
    help="Folder to write the files to.",
    required=True,
)
@click.option(
    "--features",
    "-f",
    is_flag=True,
    type=click.BOOL,
    help="Create seperate GeoJSON Feature files.",
    default=False,
)
@click.option(
    "--num",
    "-n",
    type=click.IntRange(min=1),
    help="Number of features to export. Defaults to all.",
    default=None,
)
@click.option(
    "--indent",
    "-i",
    type=click.IntRange(min=0, max=8),
    help="Indentation for JSON files. Defaults to no indentation.",
    default=None,
)
def create_geojson(file, out, features=False, num=None, indent=None):
    """
    Create a Vecorel GeoJSON file(s) from a Vecorel GeoParquet file
    """
    log(f"Vecorel CLI {__version__} - Create GeoJSON\n", "success")
    try:
        create_geojson_(file, out, features, num, indent)
        abs_path = os.path.abspath(out)
        log(f"Files written to {abs_path}", "success")
    except Exception as e:
        log(e, "error")
        sys.exit(1)


## JSON SCHEMA
@click.command()
@click.option(
    "--schema",
    "-s",
    type=click.STRING,
    callback=valid_file_for_cli,
    help=f"Vecorel schema to create the JSON Schema for. Can be a local file or a URL. If not provided, loads the schema for Vecorel version {vecorel_version_}.",
    show_default=True,
    default=VECOREL_SPECIFICAION_SCHEMA.format(version=vecorel_version_),
)
@click.option(
    "--datatypes",
    "-d",
    type=click.STRING,
    callback=valid_file_for_cli,
    help=f"Schema for the Vecorel GeoJSON datatypes. Can be a local file or a URL. If not provided, loads the GeoJSON datatypes for Vecorel version {vecorel_version_}.",
    show_default=True,
    default=VECOREL_GEOJSON_DATATYPES_SCHEMA.format(version=vecorel_version_),
)
@click.option(
    "--out",
    "-o",
    type=click.Path(exists=False),
    help="Path to write the file to. If not provided, prints the file to the STDOUT.",
    default=None,
)
@click.option(
    "--id",
    "-i",
    "id_",
    type=click.STRING,
    help="The JSON Schema $id to use for the schema. If not provided, the $id will be omitted.",
    default=None,
)
def jsonschema(schema, datatypes, out, id_):
    """
    Create a JSON Schema for a Vecorel Schema
    """
    creator = CreateJsonSchema()
    jsonschema = creator.run(schema, datatypes, out=out, schema_id=id_)
    if out:
        creator.log(f"JSON Schema written to {out}", "success")
    else:
        print(jsonschema)


## CONVERT
@click.command()
@click.argument("dataset", nargs=1, type=click.Choice(list_all_converter_ids()))
@click.option(
    "--out",
    "-o",
    type=click.Path(exists=False),
    help="Path to write the GeoParquet file to.",
    required=True,
)
@click.option(
    "--input",
    "-i",
    type=click.STRING,
    help="File(s) or URL(s) to read from. Can be used multiple times. Specific files from ZIP and 7Z archives can be picked by providing the archive path and the file path in the archive separated by a pipe sign. To pick multiple files from a single archive separate them by comma. Example: /path/to/archive.zip|file1.gpkg,subfolder/file2.gpkg",
    callback=parse_converter_input_files,
    multiple=True,
    default=None,
)
@click.option(
    "--year",
    type=click.INT,
    help="Choose a specific year to read data from. Default is the latest available year.",
)
@click.option(
    "--cache",
    "-c",
    type=click.Path(exists=False),
    help="By default the CLI downloads the source data on every execution. Specify a local folder to avoid downloading the files again. If the files exist, reads from there, otherwise stores the files there.",
    default=None,
)
@click.option(
    "--source-coop",
    "-h",
    type=click.STRING,
    help="(Future) URL to the source cooperative repository, will be added to the Collection metadata.",
    default=None,
)
@click.option(
    "--collection",
    is_flag=True,
    type=click.BOOL,
    help="Export a Collection JSON alongside the data file.",
    default=False,
)
@click.option(
    "--compression",
    "-pc",
    type=click.Choice(COMPRESSION_METHODS),
    help="Compression method for the Parquet file.",
    show_default=True,
    default="brotli",
)
@click.option(
    "--geoparquet1",
    "-gp1",
    is_flag=True,
    type=click.BOOL,
    help="Enforces generating a GeoParquet 1.0 file. Defaults to GeoParquet 1.1 with bounding box.",
    default=False,
)
@click.option(
    "--mapping-file",
    "-m",
    type=click.STRING,
    help="Url of mapping file. Some converters use additional sources with mapping data.",
    default=None,
)
@click.option(
    "--original-geometries",
    "-og",
    is_flag=True,
    type=click.BOOL,
    help="Keep the source geometries as provided, i.e. this option disables that geomtries are made valid and converted to Polygons.",
    default=False,
)
def convert(
    dataset,
    out,
    input,
    year,
    cache,
    source_coop,
    collection,
    compression,
    geoparquet1,
    mapping_file,
    original_geometries,
):
    """
    Converts existing field boundary datasets to Vecorel.
    """
    log(f"Vecorel CLI {__version__} - Convert '{dataset}'\n", "success")
    try:
        convert_(
            dataset,
            out,
            input,
            year,
            cache,
            source_coop,
            collection,
            compression,
            geoparquet1,
            mapping_file,
            original_geometries,
        )
    except Exception as e:
        log(e, "error")
        sys.exit(1)


## CONVERTERS
@click.command()
@click.option(
    "--providers",
    "-p",
    is_flag=True,
    type=click.BOOL,
    help="Show the provider name(s)",
    default=False,
)
@click.option(
    "--sources", "-s", is_flag=True, type=click.BOOL, help="Show the source(s)", default=False
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    type=click.BOOL,
    help="Does not shorten the content of the columns",
    default=False,
)
def converters(providers, sources, verbose):
    """
    Lists all available converters.
    """
    log(f"Vecorel CLI {__version__} - List of Converters\n", "success")

    columns = {"SHORT_NAME": "Short Title", "LICENSE": "License"}
    if providers:
        columns["PROVIDERS"] = "Provider(s)"
    if sources:
        columns["SOURCES"] = "Source(s)"

    keys = list(columns.keys())
    converters = list_all_converters(keys)
    df = pd.DataFrame.from_dict(converters, orient="index", columns=keys)
    df.rename(columns=columns, inplace=True)

    pd.set_option("display.max_columns", None)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_colwidth", None if verbose else 35)

    log(df)


## RENAME EXTENSION
@click.command()
@click.argument("folder", nargs=1, callback=valid_folder_for_cli)
@click.option(
    "--title",
    "-t",
    type=click.STRING,
    help="Title of the extension, e.g. `Timestamps`",
    required=True,
)
@click.option(
    "--slug",
    "-s",
    type=click.STRING,
    help="Slug of the repository, e.g. for `https://github.com/vecorel/xyz-extension` it would be `xyz-extension`",
    required=True,
)
@click.option(
    "--org",
    "-o",
    type=click.STRING,
    help="Slug of the organization, e.g. for `https://github.com/vecorel/xyz-extension` it would be `vecorel`",
    show_default=True,
    default="vecorel",
)
@click.option(
    "--prefix",
    "-p",
    type=click.STRING,
    help="Prefix for the field, e.g. `time` if the fields should be `time:created` or `time:updated`. An empty string removes the prefix, not providing a prefix leaves it as is.",
    default=None,
)
def rename_extension(folder, title, slug, org="vecorel", prefix=None):
    """
    Updates placeholders in an extension folder to the new name.
    """
    RenameExtension(title, slug, org, prefix).run(folder=folder)


## MERGE
@click.command()
@click.argument("datasets", nargs=-1, type=click.Path(exists=True))
@click.option(
    "--out",
    "-o",
    type=click.Path(exists=False),
    help="Path to write the GeoParquet file to.",
    required=True,
)
@click.option(
    "--crs",
    type=click.STRING,
    help="Coordinate Reference System (CRS) to use for the GeoParquet file.",
    show_default=True,
    default=DEFAULT_CRS,
)
@click.option(
    "--include",
    "-i",
    type=click.STRING,
    multiple=True,
    help="Additional column names to include.",
    show_default=True,
    default=CORE_COLUMNS,
)
@click.option(
    "--exclude",
    "-e",
    type=click.STRING,
    multiple=True,
    help="Default column names to exclude.",
    default=[],
)
@click.option(
    "--extension", "-x", type=click.STRING, multiple=True, help="Extensions to include.", default=[]
)
@click.option(
    "--compression",
    "-pc",
    type=click.Choice(COMPRESSION_METHODS),
    help="Compression method for the Parquet file.",
    show_default=True,
    default="brotli",
)
@click.option(
    "--geoparquet1",
    "-gp1",
    is_flag=True,
    type=click.BOOL,
    help="Enforces generating a GeoParquet 1.0 file. Defaults to GeoParquet 1.1 with bounding box.",
    default=False,
)
def merge(datasets, out, crs, include, exclude, extension, compression, geoparquet1):
    """
    Merges multiple Vecorel datasets to a combined Vecorel dataset.

    This simply appends the datasets to each other.
    It does not check for duplicates or other constraints.
    It adds a collection column to discriminate the source of the rows.
    """
    log(f"Vecorel CLI {__version__} - Merge datasets\n", "success")
    try:
        merge_(datasets, out, crs, include, exclude, list(extension), compression, geoparquet1)
    except Exception as e:
        log(e, "error")
        sys.exit(1)


## IMPROVE (add area, perimeter, fix geometries, etc.)
@click.command()
@click.argument("input", nargs=1, type=click.Path(exists=True))
@click.option(
    "--out",
    "-o",
    type=click.Path(exists=False),
    help="Path to write the GeoParquet file to. If not given, overwrites the input file.",
    default=None,
)
@click.option(
    "--rename-column",
    "-r",
    type=click.STRING,
    callback=lambda ctx, param, value: parse_map(value),
    multiple=True,
    help="Renaming of columns. Provide the old name and the new name separated by an equal sign. Can be used multiple times.",
)
@click.option(
    "--add-sizes",
    "-sz",
    is_flag=True,
    type=click.BOOL,
    help="Computes missing sizes (area, perimeter)",
    default=False,
)
@click.option(
    "--fix-geometries",
    "-g",
    is_flag=True,
    type=click.BOOL,
    help="Tries to fix invalid geometries that are repored by the validator (uses GeoPanda's make_valid method internally)",
    default=False,
)
@click.option(
    "--explode-geometries",
    "-e",
    is_flag=True,
    type=click.BOOL,
    help="Converts MultiPolygons to Polygons",
    default=False,
)
@click.option(
    "--crs",
    type=click.STRING,
    help="Coordinate Reference System (CRS) to use for the GeoParquet file.",
    show_default=True,
    default=None,
)
@click.option(
    "--compression",
    "-pc",
    type=click.Choice(COMPRESSION_METHODS),
    help="Compression method for the Parquet file.",
    show_default=True,
    default="brotli",
)
@click.option(
    "--geoparquet1",
    "-gp1",
    is_flag=True,
    type=click.BOOL,
    help="Enforces generating a GeoParquet 1.0 file. Defaults to GeoParquet 1.1 with bounding box.",
    default=False,
)
def improve(
    input,
    out,
    rename_column,
    add_sizes,
    fix_geometries,
    explode_geometries,
    crs,
    compression,
    geoparquet1,
):
    """
    "Improves" a Vecorel GeoParquet file according to the given parameters.
    """
    ImproveData().run(
        input,
        out,
        compression=compression,
        geoparquet1=geoparquet1,
        rename_columns=rename_column,
        add_sizes=add_sizes,
        fix_geometries=fix_geometries,
        explode_geometries=explode_geometries,
        crs=crs,
    )


cli.add_command(describe)
cli.add_command(validate)
cli.add_command(validate_schema)
cli.add_command(create_geoparquet)
cli.add_command(create_geojson)
cli.add_command(jsonschema)
cli.add_command(convert)
cli.add_command(converters)
cli.add_command(rename_extension)
cli.add_command(merge)
cli.add_command(improve)

if __name__ == "__main__":
    cli()
