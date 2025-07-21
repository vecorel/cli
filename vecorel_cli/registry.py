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
    The package name of the CLI.
    This is the name of the folder in which the source files are located.
    """
    package: str = "vecorel_cli"

    # todo: in fiboa CLI add "area", "perimeter", "determination_datetime", "determination_method"
    core_columns = [
        "id",
        "geometry",
        "collection",
    ]

    # The filenames for datasets (converters) that should be ignored by the CLI.
    # Always ignores files with a starting "." or "__"
    ignored_datasets = [
        "template.py",
    ]

    @staticmethod
    def get_encodings():
        """
        Returns the list of supported encodings.
        """
        from .encoding.geojson import GeoJSON
        from .encoding.geoparquet import GeoParquet

        return [
            GeoJSON,
            GeoParquet,
        ]

    @staticmethod
    def get_commands():
        """
        The commands that are made available by the CLI.
        """
        from .convert import ConvertData
        from .converters import Converters
        from .create_geojson import CreateGeoJson
        from .create_jsonschema import CreateJsonSchema
        from .describe import DescribeFile
        from .improve import ImproveData
        from .merge import MergeDatasets
        from .rename_extension import RenameExtension
        from .validate_schema import ValidateSchema

        return [
            ConvertData,
            Converters,
            CreateGeoJson,
            CreateJsonSchema,
            DescribeFile,
            ImproveData,
            MergeDatasets,
            RenameExtension,
            ValidateSchema,
        ]
