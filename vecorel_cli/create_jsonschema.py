import copy
from pathlib import Path
from typing import Optional, Union

import click
from yarl import URL

from .basecommand import BaseCommand, runnable
from .cli.options import JSON_INDENT, VECOREL_TARGET_CONSOLE
from .cli.path_url import PathOrURL
from .encoding.geojson import GeoJSON
from .jsonschema.template import jsonschema_template
from .vecorel.schemas import Schemas
from .vecorel.util import load_file
from .vecorel.version import vecorel_version


class CreateJsonSchema(BaseCommand):
    cmd_name = "jsonschema"
    cmd_title: str = "Create JSON Schema"
    cmd_help: str = "Create a JSON Schema for a Vecorel Schema"
    cmd_final_report: bool = True

    @staticmethod
    def get_cli_args():
        return {
            "schema": click.option(
                "--schema",
                "-s",
                "schema_uri",
                type=PathOrURL(extensions=[".json"]),
                help=f"Vecorel schema to create the JSON Schema for. Can be a local file or a URL. If not provided, loads the schema for Vecorel version {vecorel_version}.",
                show_default=True,
                default=Schemas.get_core_uri(vecorel_version),
            ),
            "datatypes": click.option(
                "--datatypes",
                "-d",
                "datatypes_uri",
                type=PathOrURL(extensions=[".json"]),
                help=f"Schema for the Vecorel GeoJSON datatypes. Can be a local file or a URL. If not provided, loads the GeoJSON datatypes for Vecorel version {vecorel_version}.",
                show_default=True,
                default=GeoJSON.get_datatypes_uri(vecorel_version),
            ),
            "target": VECOREL_TARGET_CONSOLE,
            "id": click.option(
                "--id",
                "-i",
                "schema_id",
                type=click.STRING,
                help="The JSON Schema $id to use for the schema. If not provided, the $id will be omitted.",
                default=None,
            ),
            "indent": JSON_INDENT,
        }

    @runnable
    def create_cli(
        self,
        schema_uri: Union[Path, URL, str],
        datatypes_uri: Union[Path, URL, str],
        target: Optional[Union[str, Path]] = None,
        schema_id: Optional[str] = None,
        indent: Optional[int] = None,
    ) -> Union[Path, str]:
        jsonschema = self.create_from_file(schema_uri, datatypes_uri, schema_id=schema_id)
        return self._json_dump_cli(jsonschema, target, indent)

    def create_from_file(
        self,
        schema_uri: str,
        datatypes_uri: str,
        schema_id: Optional[str] = None,
    ) -> dict:
        schema = load_file(schema_uri)
        datatypes = GeoJSON.load_datatypes(datatypes_uri)
        return self.create_from_dict(schema, datatypes, schema_id)

    def create_from_dict(self, schema: dict, datatypes: dict, schema_id=None):
        required = schema.get("required", [])
        collection = schema.get("collection", {})
        properties = schema.get("properties", {}).copy()
        for key, prop_schema in properties.items():
            properties[key] = self.convert_schema(prop_schema, datatypes)

        return jsonschema_template(properties, set(required), collection, schema_id)

    def convert_schema(self, prop_schema, datatypes, required=False):
        if not isinstance(prop_schema, dict) or "type" not in prop_schema:
            return prop_schema
        elif prop_schema["type"] not in datatypes:
            raise ValueError(f"Unknown datatype {prop_schema['type']}")

        datatype_schema = copy.deepcopy(datatypes[prop_schema["type"]])

        if prop_schema["type"] == "geometry":
            geom_types = prop_schema.get("geometryTypes", [])
            if isinstance(prop_schema.get("geometryTypes"), list):
                datatype_schema = {
                    "anyOf": [
                        {"$ref": f"https://geojson.org/schema/{type}.json"} for type in geom_types
                    ]
                }
                prop_schema.pop("geometryTypes", None)

        # Avoid conflicting statements
        if "exclusiveMaximum" in prop_schema:
            datatype_schema.pop("maximum", None)
        if "exclusiveMinimum" in prop_schema:
            datatype_schema.pop("minimum", None)
        if "maximum" in prop_schema:
            datatype_schema.pop("exclusiveMaximum", None)
        if "minimum" in prop_schema:
            datatype_schema.pop("exclusiveMinimum", None)

        # Deep merge schemas
        for key, value in prop_schema.items():
            if key == "items" and isinstance(value, dict):
                schema = self.convert_schema(value, datatypes)
                datatype_schema["items"] = {**datatype_schema.get("items", {}), **schema}
            elif key == "properties" and isinstance(value, dict):
                if not isinstance(datatype_schema.get("properties"), dict):
                    datatype_schema["properties"] = {}
                if not isinstance(datatype_schema.get("required"), list):
                    datatype_schema["required"] = []
                for prop_name, prop_value in value.items():
                    required = key in value.get("required", [])
                    schema = self.convert_schema(prop_value, datatypes, required)
                    datatype_schema["properties"][prop_name] = {
                        **datatype_schema["properties"].get(prop_name, {}),
                        **schema,
                    }
                    if required:
                        datatype_schema["required"].append(prop_name)
            elif key not in ["type", "required"]:
                datatype_schema[key] = value

        return datatype_schema
