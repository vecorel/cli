# TEMPLATE FOR A VECOREL CONVERTER
#
# Copy this file and rename it to something sensible.
# The name of the file will be the name of the converter in the cli.
# If you name it 'de_abc' you'll be able to run `vec convert de_abc` in the cli.

from ..conversion.base import BaseConverter

# You can remove attributes that you don't need.
# Also, please remove all comments that you didn't add yourself from the template.


class Converter(BaseConverter):
    # File(s) to read the data from, usually publicly accessible URLs.
    # Can read any (zipped) tabular data format that GeoPandas can read through read_file() or read_parquet().
    # Supported protocols: HTTP(S), GCS, S3, or the local file system

    # Multiple options are possible:
    # 1. a single URL (filename must be in the URL). The file is read as is.
    sources = "https://vecorel.example/data.shp.zip"

    # 2. a dictionary with a mapping of URLs (where the filename can't necessarily be determined from the URL) to filenames.
    # sources = {
    #   "https://vecorel.example/archive/758?download=1": "us.gpkg"
    #   "https://vecorel.example/archive/355?download=1": "canada.gpkg"
    # }
    # 3. a dictionary with a mapping of URLs to a list of filenames in ZIP ot 7Z files to read from.
    # sources = {
    #   "https://vecorel.example/north_america.zip": ["us.gpkg", "canaga.gpkg"]
    # }

    # 4. if multiple variants (e.g. years) are available, you can replace sources by the variants.
    # The dict-key can be used on the cli command line, the value will be used as 'sources'
    #
    # variants = {
    #    "2023": "https://vecorel.example/file_2023.xyz"
    #    "2024": "https://vecorel.example/file_2024.xyz"
    # }

    # Override filter function for the layer in the file(s) to read.
    # def layer_filter(self, layer: str, uri: str) -> bool:
    #     return True

    # Unique identifier for the collection
    id = "abc"
    # Geonames for the data (e.g. Country, Region, Source, Year)
    short_name = "Country, Region, etc."
    # Title of the collection
    title = "Field boundaries for Country, Region, etc."
    # Description of the collection. Can be multiline and include CommonMark.
    description = """Describe the dataset here."""

    # The provider of the data.
    # A string that contains the provider name and optionally a URL.
    # Either "Name" or "Name <URL>".
    provider = "ABC Corp <https://abc.example>"

    # Attribution (e.g. copyright or citation statement as requested by provider) as a string.
    # The attribution is usually shown on the map, in the lower right corner.
    # Can be None if not applicable
    attribution = "© 2024 ABC Corp."

    # License of the data, either
    # 1. a SPDX license identifier (including "dl-de/by-2-0" / "dl-de/zero-2-0"), or
    # 2. a string with license name and URL, e.g. "My License <https://my.com/license>"
    license = "CC-BY-4.0"

    # Map original column names to Vecorel property names
    # You also need to list any column that you may have added in the MIGRATION function (see below).
    # GeoJSON: Nested objects can be accessed using a dot, e.g. "area.value" for {"area": {"value": 123}}
    columns = {
        "some_are_col": "area",
        "geom": "geometry",
    }

    # Add columns with constant values.
    # The key is the column name, the value is a constant value that's used for all rows.
    column_additions = {}

    # A set of implemented extension identifiers
    extensions = {"https://vecorel.github.io/administrative-division-extension/v0.1.0/schema.yaml"}

    # Functions to migrate data in columns to match the Vecorel specification.
    # Example: You have a column area_m in square meters and want to convert
    # to hectares as required for the area field in Vecorel.
    # requires: func(column: pd.Series) -> pd.Series
    column_migrations = {"area_m": lambda column: column * 0.0001}

    # Filter columns to only include the ones that are relevant for the collection,
    # e.g. only rows that contain the word "agriculture" but not "forest" in the column "land_cover_type".
    # Lamda function accepts a Pandas Series and returns a Series or a Tuple with a Series and True to inverse the mask.
    column_filters = {"land_cover_type": lambda col: (col.isin(["agrictulture"]), True)}

    # Override to migrate the full GeoDataFrame if the other options are not sufficient
    # This should be the last resort!
    # def migrate(self, gdf) -> gpd.GeoDataFrame:
    #     gdf["column"] *= 10
    #     return gdf

    # Custom function to execute actions on the the GeoDataFrame that are loaded from individual file or layers.
    # This is useful if the data is split into multiple files/layers and columns should be added or changed
    # on a per-file/layer basis for example.
    # The path contains the local path to the file that was read.
    # The uri contains the URL that was read.
    # The layer may contain the layer name.
    # def file_migration(self, gdf: gpd.GeoDataFrame, path: str, uri: str, layer: str = None) -> gpd.GeoDataFrame:
    #     return data

    # Schemas for the fields that are not defined in the core or the used extensions
    # Keys must be the values from the COLUMNS dict, not the keys
    missing_schemas = {
        "required": ["my_id"],  # i.e. non-nullable properties
        "properties": {
            "some_col": {"type": "string"},
            "category": {"type": "string", "enum": ["A", "B"]},
        },
    }
