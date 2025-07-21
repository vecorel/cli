from .basecommand import BaseCommand
from .cli.util import log
from .converters import Converters


class ConvertData(BaseCommand):
    cmd_name = "create-geojson"
    cmd_title = "Create GeoJSON"
    cmd_help = "Converts to GeoJSON file(s) from other compatible files."
    cmd_final_report = True

    @staticmethod
    def get_cli_args():
        return {
            # todo
        }


def convert(
    dataset,
    output_file,
    input_files=None,
    year=None,
    cache=None,
    source_coop_url=None,
    collection=False,
    compression=None,
    geoparquet1=False,
    mapping_file=None,
    original_geometries=False,
):
    converters = Converters()
    if converters.is_converter(dataset):
        raise Exception(f"'{dataset}' is not a converter")
    try:
        converter = converters.load(dataset)
    except ImportError as e:
        raise Exception(f"Converter for '{dataset}' not available or faulty: {e}")

    if hasattr(converter, "DATA_ACCESS") and not cache and not input_files:
        log(
            "Data access is restricted. You need to manually get the data from the source.",
            "warning",
        )
        log("Instructions for data access:", "warning")
        log(converter.DATA_ACCESS.strip(), "info")
        raise Exception("Provide the file through the `-i` parameter.")

    converter.convert(
        output_file,
        input_files=input_files,
        year=year,
        cache=cache,
        source_coop_url=source_coop_url,
        store_collection=collection,
        compression=compression,
        geoparquet1=geoparquet1,
        mapping_file=mapping_file,
        original_geometries=original_geometries,
    )
