from .encoding.geojson import GeoJSON
from .encoding.geoparquet import GeoParquet
from .version import __version__


class Registry:
    """
    The displayable title of the CLI.
    """

    cli_title: str = "Vecorel CLI"

    """
    The version number of the CLI.
    """
    cli_version: str = __version__

    """
    The supported encodings for file formats.
    """
    encodings = [
        GeoJSON,
        GeoParquet,
    ]

    # todo: in fiboa CLI add "area", "perimeter", "determination_datetime", "determination_method"
    core_columns = [
        "id",
        "geometry",
        "collection",
    ]

    @staticmethod
    def get_commands():
        """
        The commands that are made available by the CLI.
        """
        from .create_geojson import CreateGeoJson
        from .create_jsonschema import CreateJsonSchema
        from .describe import DescribeFile
        from .improve import ImproveData
        from .merge import MergeDatasets
        from .rename_extension import RenameExtension
        from .validate_schema import ValidateSchema

        return [
            CreateGeoJson,
            CreateJsonSchema,
            DescribeFile,
            ImproveData,
            MergeDatasets,
            RenameExtension,
            ValidateSchema,
        ]
