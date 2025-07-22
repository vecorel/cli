import json
from pathlib import Path
from typing import Optional, Union

import click

from .basecommand import BaseCommand, runnable
from .cli.util import valid_file
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
                type=click.STRING,
                callback=valid_file,
                help=f"Vecorel schema to create the JSON Schema for. Can be a local file or a URL. If not provided, loads the schema for Vecorel version {vecorel_version}.",
                show_default=True,
                default=Schemas.get_core_uri(vecorel_version),
            ),
            "datatypes": click.option(
                "--datatypes",
                "-d",
                "datatypes_uri",
                type=click.STRING,
                callback=valid_file,
                help=f"Schema for the Vecorel GeoJSON datatypes. Can be a local file or a URL. If not provided, loads the GeoJSON datatypes for Vecorel version {vecorel_version}.",
                show_default=True,
                default=GeoJSON.get_datatypes_uri(vecorel_version),
            ),
            "out": click.option(
                "--out",
                "-o",
                type=click.Path(exists=False),
                help="Path to write the file to. If not provided, prints the schema to the console.",
                default=None,
            ),
            "id": click.option(
                "--id",
                "-i",
                "schema_id",
                type=click.STRING,
                help="The JSON Schema $id to use for the schema. If not provided, the $id will be omitted.",
                default=None,
            ),
        }

    @runnable
    def create_from_files(
        self,
        schema_uri: str,
        datatypes_uri: str,
        out: Optional[str] = None,
        schema_id: Optional[str] = None,
    ) -> Union[Path, dict]:
        schema = load_file(schema_uri)
        datatypes = GeoJSON.load_datatypes(datatypes_uri)
        jsonschema = self.create_from_dict(schema, datatypes, schema_id)
        if out:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(jsonschema, f, indent=2)
            return out
        else:
            return jsonschema

    def create_from_dict(self, schema: dict, datatypes: dict, schema_id=None):
        required = schema.get("required", [])
        properties = {}
        for key, prop_schema in schema.get("properties", {}).items():
            properties[key] = self.convert_schema(prop_schema, datatypes, key in required)

        return jsonschema_template(properties, required, schema_id)

    def convert_schema(self, prop_schema, datatypes, required=False):
        if not isinstance(prop_schema, dict) or "type" not in prop_schema:
            return prop_schema
        elif prop_schema["type"] not in datatypes:
            raise ValueError(f"Unknown datatype {prop_schema['type']}")

        datatype_schema = datatypes[prop_schema["type"]].copy()

        if prop_schema["type"] == "geometry":
            geom_types = prop_schema.get("geometryTypes", [])
            if isinstance(prop_schema.get("geometryTypes"), list):
                datatype_schema = {
                    "anyOf": [
                        {"$ref": f"https://geojson.org/schema/{type}.json"} for type in geom_types
                    ]
                }
                del prop_schema["geometryTypes"]

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
