import re


class Schemas:
    spec_pattern = r"https://vecorel.github.io/specification/v([^/]+)/schema.yaml"
    spec_schema = "https://vecorel.github.io/specification/v{version}/schema.yaml"

    @staticmethod
    def get_core_uri(version: str) -> str:
        return Schemas.spec_schema.format(version=version)

    def __init__(self, schemas: list[str] = [], collection=None):
        self.schemas = set(schemas)
        self.collection = collection

    def get_all(self) -> list[str]:
        return list(self.schemas)

    def remove(self, schema_uri: str) -> None:
        self.schemas.remove(schema_uri)

    def add(self, schema_uri: str) -> None:
        self.schemas.add(schema_uri)

    def get(self) -> tuple[str, str, list[str]]:
        uri = None
        version = None
        extensions = []
        for schema in self.schemas:
            potential_version = self._parse_version(schema)
            if potential_version is None:
                extensions.append(schema)
            else:
                uri = schema
                version = potential_version

        extensions.sort()
        return version, uri, extensions

    def get_core_version(self) -> str:
        version, uri, extensions = self.get()
        return version

    def get_core_schema_uri(self):
        version, uri, extensions = self.get()
        return uri

    def get_extensions(self) -> list[str]:
        version, uri, extensions = self.get()
        return extensions

    def _parse_version(self, schema_uri: str):
        match = re.match(self.spec_pattern, schema_uri)
        return match.group(1) if match else None
