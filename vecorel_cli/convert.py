import click

from .basecommand import BaseCommand, runnable
from .cli.options import GEOPARQUET_COMPRESSION, GEOPARQUET_VERSION
from .cli.util import parse_converter_input_files
from .converters import Converters


class ConvertData(BaseCommand):
    cmd_name = "convert"
    cmd_help = "Converts existing non-Vecorel datasets to Vecorel."
    cmd_final_report = True

    @staticmethod
    def get_cli_args():
        c = Converters()
        return {
            "dataset": click.argument("dataset", nargs=1, type=click.Choice(c.list_ids())),
            "out": click.option(
                "--out",
                "-o",
                type=click.Path(exists=False),
                help="Path to write the GeoParquet file to.",
                required=True,
            ),
            "input": click.option(
                "--input",
                "-i",
                type=click.STRING,
                help="File(s) or URL(s) to read from. Can be used multiple times. Specific files from ZIP and 7Z archives can be picked by providing the archive path and the file path in the archive separated by a pipe sign. To pick multiple files from a single archive separate them by comma. Example: /path/to/archive.zip|file1.gpkg,subfolder/file2.gpkg",
                callback=parse_converter_input_files,
                multiple=True,
                default=None,
            ),
            "year": click.option(
                "--year",
                type=click.INT,
                help="Choose a specific year to read data from. Default is the latest available year.",
            ),
            "cache": click.option(
                "--cache",
                "-c",
                type=click.Path(exists=False),
                help="By default the CLI downloads the source data on every execution. Specify a local folder to avoid downloading the files again. If the files exist, reads from there, otherwise stores the files there.",
                default=None,
            ),
            "source_coop": click.option(
                "--source-coop",
                "-h",
                type=click.STRING,
                help="(Future) URL to the source cooperative repository, will be added to the Collection metadata.",
                default=None,
            ),
            "collection": click.option(
                "--collection",
                is_flag=True,
                type=click.BOOL,
                help="Export a Collection JSON alongside the data file.",
                default=False,
            ),
            "compression": GEOPARQUET_COMPRESSION,
            "geoparquet_version": GEOPARQUET_VERSION,
            "mapping_file": click.option(
                "--mapping-file",
                "-m",
                type=click.STRING,
                help="URL of mapping file. Some converters use additional sources with mapping data.",
                default=None,
            ),
            "original_geometries": click.option(
                "--original-geometries",
                "-og",
                is_flag=True,
                type=click.BOOL,
                help="Keep the source geometries as provided, i.e. this option disables that geomtries are made valid and converted to Polygons.",
                default=False,
            ),
        }

    @staticmethod
    def get_cli_callback(cmd):
        def callback(*args, **kwargs):
            return ConvertData(cmd.dataset).convert(*args, **kwargs)

        return callback

    def __init__(self, dataset: str):
        self.cmd_title = f"Convert {dataset}"
        self.dataset = dataset

        converters = Converters()
        if converters.is_converter(self.dataset):
            raise Exception(f"'{self.dataset}' is not a converter")
        try:
            self.converter = converters.load(self.dataset)
        except ImportError as e:
            raise Exception(f"Converter for '{self.dataset}' not available or faulty: {e}")

    @runnable
    def convert(
        self,
        output_file,
        input_files=None,
        year=None,
        cache=None,
        source_coop_url=None,
        collection=False,
        compression=None,
        geoparquet_version=None,
        mapping_file=None,
        original_geometries=False,
    ):
        if hasattr(self.converter, "DATA_ACCESS") and not cache and not input_files:
            self.log(
                "Data access is restricted. You need to manually get the data from the source.",
                "warning",
            )
            self.log("Instructions for data access:", "warning")
            self.log(self.converter.DATA_ACCESS.strip(), "info")
            raise Exception("Provide the file through the `-i` parameter.")

        self.converter.convert(
            output_file,
            input_files=input_files,
            year=year,
            cache=cache,
            source_coop_url=source_coop_url,
            store_collection=collection,
            compression=compression,
            geoparquet_version=geoparquet_version,
            mapping_file=mapping_file,
            original_geometries=original_geometries,
        )
