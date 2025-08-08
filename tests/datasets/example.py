from vecorel_cli.conversion.admin import AdminConverterMixin
from vecorel_cli.conversion.base import BaseConverter


class Converter(AdminConverterMixin, BaseConverter):
    sources = "https://service.gdi-sh.de/SH_OpenGBD/feeds/Atom_SH_Feldblockfinder_OpenGBD/data/Feldbloecke_2024_GPKG.zip"
    id = "de_sh"
    admin_subdivision_code = "SH"
    short_name = "Germany, Schleswig-Holstein"
    title = "Field boundaries for Schleswig-Holstein (SH), Germany"
    description = """A field block (German: "Feldblock") is a contiguous agricultural area surrounded by permanent boundaries, which is cultivated by one or more farmers with one or more crops, is fully or partially set aside or is fully or partially taken out of production."""
    provider = "Land Schleswig-Holstein <https://sh-mis.gdi-sh.de/catalog/#/datasets/iso/21f67269-780f-4f3c-8f66-03dde27acfe7>"
    license = "dl-de/zero-2-0"
    columns = {
        "geometry": "geometry",
        "fachguelti": "determination_datetime",
        "FLIK": ["id"],
        "Flaeche": "area",
        "HBN": "hbn",
    }
    missing_schemas = {
        "properties": {
            "hbn": {"type": "string"},
            "determination_datetime": {"type": "date-time"},
            "area": {"type": "float", "minimum": 0},
        }
    }
