import json
import sys
from typing import Union

import click
import pyarrow.types as pat

from .basecommand import BaseCommand, runnable
from .cli.options import SCHEMA_MAP
from .cli.util import get_files
from .create_jsonschema import CreateJsonSchema
from .encoding.geojson import GeoJSON
from .encoding.geoparquet import GeoParquet
from .jsonschema.util import merge_schemas
from .parquet.types import PA_TYPE_CHECK
from .registry import Registry
from .validate_schema import ValidateSchema
from .vecorel.schemas import Schemas
from .vecorel.util import load_file
from .vecorel.version import is_supported, supported_vecorel_versions


class ValidateData(BaseCommand):
    cmd_name = "validate"
    cmd_title: str = "Validator"
    cmd_help: str = "Validates a Vecorel data file."

    @staticmethod
    def get_cli_args():
        return {
            "files": click.argument(
                "files",
                nargs=-1,
                callback=lambda ctx, param, value: get_files(
                    value, Registry.get_vecorel_extensions()
                ),
            ),
            "data": click.option(
                "--data",
                "-d",
                is_flag=True,
                type=click.BOOL,
                help="EXPERIMENTAL: Validate the data in the GeoParquet file. Enabling this might be slow or exceed memory. Default is False.",
                default=False,
            ),
            "schemas": SCHEMA_MAP,
        }

    @runnable
    def validate(self, files, data, schemas):
        """
        Validates a Vecorel GeoParquet or GeoJSON file.
        """
        config = {
            "schemas": schemas,
            "data": data,
        }

        if len(files) == 0:
            self.log("No files to validate", "error")
            sys.exit(1)

        exit = 0
        for file in files:
            self.log(f"Validating {file}", "info")
            try:
                result = self.validate_file(file, config)
                if result:
                    self.log("\n  => VALID\n", "success")
                else:
                    self.log("\n  => INVALID\n", "error")
                    exit = 1
            except Exception as e:
                self.log(f"\n  => UNKNOWN: {e}\n", "error")
                exit = 2

        sys.exit(exit)

    # todo: make usable outside of CLI (e.g. logging)
    def log(self, text: Union[str, Exception], status="info", nl=True, **kwargs):
        # Indent logs
        super().log("  - " + str(text), status, nl, **kwargs)

    def validate_file(self, file, config):
        if file.endswith(".json") or file.endswith(".geojson"):
            return self.validate_geojson(file, config)
        else:
            return self.validate_parquet(file, config)

    def validate_schemas(self, schemas: Schemas, config):
        valid = True

        if not isinstance(schemas, Schemas):
            self.log("A valid Schemas object must be provided", "error")
            valid = False

        schema_uris = schemas.get_all()
        if len(schema_uris) == 0:
            self.log("No schemas provided", "error")
            valid = False

        # Detect and check fiboa version
        version = schemas.get_core_version()
        core_schema = schemas.get_core_schema_uri()

        if version is None:
            self.log(
                "Vecorel core schema not found in schemas, can't detect Vecorel version", "error"
            )
            valid = False

        # todo: use python-semanticversion to check for version ranges (e.g. allow 0.3.x)
        if not is_supported(version):
            self.log(
                f"Vecorel versions differs: Schema reports {version} and supported version is {supported_vecorel_versions}",
                "warning",
            )

        # Check schemas (core and extensions)
        schemas = {}
        schema_map = config.get("schemas", {})
        for uri in schema_uris:
            try:
                if uri in schema_map:
                    actual_location = schema_map[uri]
                    self.log(f"Redirecting {uri} to {actual_location}", "info")
                else:
                    actual_location = uri

                schemas[uri] = load_file(actual_location)
            except Exception as e:
                self.log(f"Extension {uri} can't be loaded: {e}", "error")
                valid = False

        # log_extensions(schema_uris, lambda x: log(x, "info", False))

        return valid, version, core_schema, schemas

    def validate_geojson(self, file, config):
        try:
            data = load_file(file)
        except Exception as error:
            self.log(error, "error")
            return False

        if not isinstance(data, dict):
            self.log("Must be a JSON object", "error")
            return False

        schemas_uris = {}
        collection = {}
        feature_type = data.get("type")
        if feature_type == "FeatureCollection":
            collection = data.get("fiboa", {})
            schemas_uris = collection.get("schemas", {})
            features = data["features"]
        elif feature_type == "Feature":
            schemas_uris = data.get("properties", {}).get("schemas", {})
            features = [data]
        else:
            self.log("Must be a GeoJSON Feature or FeatureCollection", "error")
            return False

        valid, version, core_schema_uri, schemas = self.validate_schemas(schemas_uris, config)

        core_schema = schemas[core_schema_uri]
        datatypes = GeoJSON.get_datatypes(version)
        jsonschema = CreateJsonSchema()
        schema = jsonschema.create_from_dict(core_schema, datatypes)

        # Load extensions
        ext_errors = []
        extensions = {}
        for ext in schemas:
            try:
                json_schema = jsonschema.create_from_dict(schemas[ext], datatypes)
                extensions[ext] = lambda obj: self.validate_json_schema(obj, json_schema)
            except Exception as error:
                extensions[ext] = None
                ext_errors.append(f"Failed to load extension {ext}: {str(error)}")

        for error in ext_errors:
            self.log(error, "error")

        # Validate
        if len(features) == 0:
            self.log("Must contain at least one Feature", "error")
            return False

        for index, feature in enumerate(features):
            errors = self.validate_json_schema(feature, schema)
            if len(errors) > 0:
                valid = False

            label = feature.get("id", f"index: {index}")

            if not valid:
                for error in errors:
                    self.log(f"{label}: {error}", "error")
            else:
                for ext, validate_fn in extensions.items():
                    if validate_fn:
                        ext_errors = validate_fn(feature)
                        if len(ext_errors) > 0:
                            for error in ext_errors:
                                self.log(f"{label} (ext {ext}): {error}", "error")
                            valid = False
                    else:
                        self.log(f"{label}: Extension {ext} SKIPPED", "warning")
                if valid and len(features) > 1:
                    self.log(f"{label}: VALID", "success")

        return valid

    def validate_parquet(self, file, config):
        pq = GeoParquet(file)
        if not self.validate_geoparquet_schema(pq):
            return False

        # Validate fiboa metadata in Parquet header
        if b"fiboa" not in pq.get_metadata():
            self.log("Parquet file schema does not have a 'fiboa' key", "error")
            return False

        collection = pq.get_collection()
        schemas = pq.get_schemas()

        valid, version, core_schema_uri, schemas = self.validate_schemas(schemas, config)

        fiboa_schema = schemas[core_schema_uri]

        # Load data if needed
        gdf = None
        if config.get("data"):
            try:
                gp = GeoParquet(file)
                gdf = gp.read()
            except Exception as e:
                self.log(f"Data could not be read: {e}", "error")
                valid = False

        # Compile all properties from the schemas
        schemas = fiboa_schema
        for ext in schemas.values():
            if core_schema_uri == ext:
                continue
            schemas = merge_schemas(schemas, ext)

        # Add custom schemas
        custom_schemas = collection.get("custom_schemas", {})
        schemas = merge_schemas(schemas, custom_schemas)

        parquet_schema = pq.get_pq_schema()
        # Check that all required fields are present
        for key in schemas.get("required", []):
            if key not in parquet_schema.names:
                self.log(f"{key}: Required field is missing", "error")
                valid = False

        # Validate whether the Parquet schema complies with the property schemas
        geo = pq.get_geo_metadata()
        properties = schemas.get("properties", {})
        for key in parquet_schema.names:
            # Ignore fields without a schema
            if key not in properties:
                self.log(f"{key}: No schema defined", "warning")
                continue

            prop_schema = properties[key]
            # Make sure the schema has a data type assigned
            dtype = prop_schema.get("type")
            if dtype is None:
                self.log(f"{key}: No type specified", "warning")
                continue

            pq_field = parquet_schema.field(key)
            pq_type = pq_field.type

            # Does the field (dis)allow null?
            nullable = key not in schemas.get("required", [])
            if nullable != pq_field.nullable:
                self.log(
                    f"{key}: Nullability differs, is {pq_field.nullable} but must be {nullable}",
                    "error",
                )
                valid = False

            # Is the data type of the field correct?
            pa_check = PA_TYPE_CHECK.get(dtype)
            if pa_check is None:
                self.log(f"{key}: Validating {dtype} is not supported yet", "warning")
                continue
            elif not pa_check(pq_type):
                self.log(f"{key}: Data type invalid, is {pq_type} but must be {dtype}", "error")
                valid = False
                continue

            # Check specifics of some types
            if dtype == "date-time":
                if pq_type.unit != "ms":
                    self.log(f"{key}: Timestamp unit differs, should be ms", "warning")
                if pq_type.tz != "UTC":
                    self.log(f"{key}: Timestamp timezone invalid, must be UTC", "error")
                    valid = False
            elif dtype == "object":
                if pat.is_map(pq_type) and not pat.is_string(pq_field.key_type):
                    self.log(f"{key}: Map keys must be strings", "error")
                    valid = False
            elif dtype == "geometry":
                valid = self.validate_geometry_column(key, prop_schema, geo, valid)

            # Validate data of the column
            if gdf is not None:
                issues = self.validate_column(gdf[key], prop_schema)
                if len(issues) > 0:
                    for issue in issues:
                        self.log(f"{key}: {issue}")
                    valid = False

        # Show a note once if data was not validated
        if not config.get("data"):
            self.log("Data was not validated as the --data parameter was not provided", "info")

        return valid

    def validate_geometry_column(self, key, prop_schema, geo, valid=True):
        columns = geo.get("columns", {})
        if key not in columns:
            self.log(f"{key}: Geometry column not found in GeoParquet metadata", "error")
            valid = False

        schema_geo_types = prop_schema.get("geometryTypes", [])
        schema_geo_types.sort()
        if len(schema_geo_types) > 0:
            gp_geo_types = columns[key].get("geometry_types", [])
            gp_geo_types.sort()
            if len(gp_geo_types) == 0:
                self.log(f"{key}: No geometry types specified in GeoParquet metadata", "warning")

            if schema_geo_types != gp_geo_types:
                self.log(
                    f"{key}: GeoParquet geometry types differ, is {gp_geo_types} but must be {schema_geo_types}",
                    "error",
                )
                valid = False

        return valid

    # todo: use a geoparquet validator instead of our own validation routine
    def validate_geoparquet_schema(self, pq: GeoParquet):
        geo = pq.get_geoparquet_metadata()
        if geo is None:
            self.log("File does not have GeoParquet metadata", "error")
            return False

        try:
            schema = pq.get_geoparquet_schema()
            errors = self.validate_json_schema(geo, schema)
            for error in errors:
                self.log(f"GeoParquet metadata: {error.path}: {error.message}", "error")

            return len(errors) == 0
        except Exception as e:
            self.log(
                f"Failed to validate GeoParquet metadata due to an internal error: {e}", "error"
            )
            return False

    def validate_json_schema(self, obj, schema):
        if isinstance(obj, (bytearray, bytes, str)):
            obj = json.loads(obj)

        validator = ValidateSchema()
        return validator.validate(obj)
