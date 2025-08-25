import importlib.metadata


class VecorelRegistry:
    """
    The public package name of the library (e.g. on pypi).
    """

    name: str = "vecorel-cli"

    """
    The displayable title of the CLI.
    """
    cli_title: str = "Vecorel CLI"

    """
    The internal package name of the CLI.
    This is the name of the folder in which the source files are located.
    """
    src_package: str = "vecorel_cli"

    # todo: in fiboa CLI add "area", "perimeter", "determination_datetime", "determination_method"
    core_properties = [
        "id",
        "geometry",
        "collection",
    ]

    # The filenames for datasets (converters) that should be ignored by the CLI.
    # Always ignores files with a starting "." or "__"
    ignored_datasets = [
        "template.py",
    ]

    def get_version(self):
        """
        Returns the version of the library/CLI.
        """
        return importlib.metadata.version(self.name)

    def get_encodings(self):
        """
        Returns the list of supported encodings.
        """
        from .encoding.geojson import GeoJSON
        from .encoding.geoparquet import GeoParquet

        return [
            GeoJSON,
            GeoParquet,
        ]

    def get_vecorel_extensions(self):
        """
        Returns the list of Vecorel extensions, each with a leading dot.
        These are the file extensions that are supported by the CLI.
        """
        extensions = []
        for encoding in self.get_encodings():
            extensions += encoding.ext

        return extensions

    def get_commands(self):
        """
        The commands that are made available by the CLI.
        """
        from .convert import ConvertData
        from .converters import Converters
        from .create_geojson import CreateGeoJson
        from .create_geoparquet import CreateGeoParquet
        from .create_jsonschema import CreateJsonSchema
        from .create_stac import CreateStacCollection
        from .describe import DescribeFile
        from .improve import ImproveData
        from .merge import MergeDatasets
        from .rename_extension import RenameExtension
        from .validate import ValidateData
        from .validate_schema import ValidateSchema

        return [
            ConvertData,
            Converters,
            CreateGeoJson,
            CreateGeoParquet,
            CreateJsonSchema,
            CreateStacCollection,
            DescribeFile,
            ImproveData,
            MergeDatasets,
            RenameExtension,
            ValidateData,
            ValidateSchema,
        ]


class RegistryMeta(type):
    """Metaclass to forward class-level attribute access to the instance."""

    def __getattr__(cls, name):
        # Forward attribute access to the instance
        return getattr(cls.instance, name)


class Registry(metaclass=RegistryMeta):
    instance = VecorelRegistry()
