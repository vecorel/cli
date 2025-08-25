import click

from .basecommand import BaseCommand, runnable
from .cli.options import GEOPARQUET_COMPRESSION, GEOPARQUET_VERSION, PY_PACKAGE, VECOREL_TARGET
from .cli.util import parse_converter_input_files
from .converters import Converters
from .registry import Registry


class ConvertData(BaseCommand):
    cmd_name = "convert"
    cmd_help = f"Converts existing non-{Registry.project} datasets to {Registry.project}."
    cmd_final_report = True
    converters = Converters()

    @staticmethod
    def check_datasets(ctx, param, value):
        package = ctx.params.get("py_package")
        if package:
            Registry.src_package = package

        ids = ConvertData.converters.list_ids()
        if value not in ids:
            available = "None" if len(ids) == 0 else ", ".join(ids)
            raise click.BadParameter(
                f"Converter '{value}' not found in '{Registry.src_package}'. Available converters: {available}"
            )
        else:
            return value

    @staticmethod
    def get_cli_args():
        return {
            "dataset": click.argument(
                "dataset",
                nargs=1,
                type=click.STRING,
                callback=ConvertData.check_datasets,
            ),
            "target": VECOREL_TARGET(),
            "input": click.option(
                "input_files",
                "--input",
                "-i",
                type=click.STRING,
                help="File(s) or URL(s) to read from. Can be used multiple times. Specific files from ZIP and 7Z archives can be picked by providing the archive path and the file path in the archive separated by a pipe sign. To pick multiple files from a single archive separate them by comma. Example: /path/to/archive.zip|file1.gpkg,subfolder/file2.gpkg",
                callback=parse_converter_input_files,
                multiple=True,
                default=None,
            ),
            "variant": click.option(
                "--variant",
                type=click.STRING,
                help="Choose a specific variant to read data from, e.g. a specific year.",
            ),
            "cache": click.option(
                "--cache",
                "-c",
                type=click.Path(exists=False),
                help="By default the CLI downloads the source data on every execution. Specify a local folder to avoid downloading the files again. If the files exist, reads from there, otherwise stores the files there.",
                default=None,
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
            "py-package": PY_PACKAGE,
        }

    @staticmethod
    def get_cli_callback(cmd):
        def callback(dataset, *args, **kwargs):
            py_package = kwargs.pop("py_package", None)
            return ConvertData(dataset, py_package).run(*args, **kwargs)

        return callback

    def __init__(self, dataset: str, py_package: str = None):
        self.cmd_title = f"Convert {dataset}"
        self.dataset = dataset

        if py_package:
            Registry.src_package = py_package

        if ConvertData.converters.is_converter(self.dataset):
            raise Exception(f"'{self.dataset}' is not a converter")
        try:
            self.converter = ConvertData.converters.load(self.dataset)
        except (ImportError, NameError, OSError, RuntimeError, SyntaxError) as e:
            raise Exception(f"Converter for '{self.dataset}' not available or faulty: {e}") from e

    @runnable
    def convert(
        self,
        target,
        input_files=None,
        variant=None,
        cache=None,
        compression=None,
        geoparquet_version=None,
        original_geometries=False,
        **kwargs,
    ):
        if len(self.converter.data_access) > 0 and not cache and not input_files:
            self.warning(
                "Data access is restricted. You need to manually get the data from the source. Provide the file through the `-i` parameter."
            )
            self.info("Instructions for data access:", start="\n", style="underline")
            self.info(self.converter.data_access.strip(), end="\n\n")
            raise Exception("Please provide the input data.")

        self.converter.convert(
            target,
            input_files=input_files,
            variant=variant,
            cache=cache,
            compression=compression,
            geoparquet_version=geoparquet_version,
            original_geometries=original_geometries,
            **kwargs,
        )
