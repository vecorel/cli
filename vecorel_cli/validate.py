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
            self.error("No files to validate")
            sys.exit(1)

        exit = 0
        for file in files:
            self.info(f"Validating {file}")
            try:
                result = self.validate_file(file, config)
                if result:
                    self.success("VALID", start="\n", end="\n", indent="  => ")
                else:
                    self.error("INVALID", start="\n", end="\n", indent="  => ")
                    exit = 1
            except Exception as e:
                self.error(f"UNKNOWN: {e}", start="\n", end="\n", indent="  => ")
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
            self.error("A valid Schemas object must be provided")
            valid = False

        schema_uris = schemas.get_all()
        if len(schema_uris) == 0:
            self.error("No schemas provided")
            valid = False

        # Detect and check fiboa version
        version = schemas.get_core_version()
        core_schema = schemas.get_core_schema_uri()

        if version is None:
            self.error("Vecorel core schema not found in schemas, can't detect Vecorel version")
            valid = False

        # todo: use python-semanticversion to check for version ranges (e.g. allow 0.3.x)
        if not is_supported(version):
            self.warning(
                f"Vecorel versions differs: Schema reports {version} and supported version is {supported_vecorel_versions}"
            )

        # Check schemas (core and extensions)
        schemas = {}
        schema_map = config.get("schemas", {})
        for uri in schema_uris:
            try:
                if uri in schema_map:
                    actual_location = schema_map[uri]
                    self.info(f"Redirecting {uri} to {actual_location}")
                else:
                    actual_location = uri

                schemas[uri] = load_file(actual_location)
            except Exception as e:
                self.error(f"Extension {uri} can't be loaded: {e}")
                valid = False

        # log_extensions(schema_uris, lambda x: log(x, "info", False))

        return valid, version, core_schema, schemas

    def validate_geojson(self, file, config):
        try:
            data = load_file(file)
        except Exception as error:
            self.exception(error)
            return False

        if not isinstance(data, dict):
            self.error("Must be a JSON object")
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
            self.error("Must be a GeoJSON Feature or FeatureCollection")
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
            self.error(error)

        # Validate
        if len(features) == 0:
            self.error("Must contain at least one Feature")
            return False

        for index, feature in enumerate(features):
            errors = self.validate_json_schema(feature, schema)
            if len(errors) > 0:
                valid = False

            label = feature.get("id", f"index: {index}")

            if not valid:
                for error in errors:
                    self.error(f"{label}: {error}")
            else:
                for ext, validate_fn in extensions.items():
                    if validate_fn:
                        ext_errors = validate_fn(feature)
                        if len(ext_errors) > 0:
                            for error in ext_errors:
                                self.error(f"{label} (ext {ext}): {error}")
                            valid = False
                    else:
                        self.warning(f"{label}: Extension {ext} SKIPPED")
                if valid and len(features) > 1:
                    self.success(f"{label}: VALID")

        return valid

    def validate_parquet(self, file, config):
        pq = GeoParquet(file)
        if not self.validate_geoparquet_schema(pq):
            return False

        # Validate collection metadata in Parquet header
        if b"collection" not in pq.get_metadata():
            self.error("Parquet file schema does not have a 'collection' key")
            return False

        # collection = pq.get_collection()
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
                self.error(f"Data could not be read: {e}")
                valid = False

        # Compile all properties from the schemas
        schemas = fiboa_schema
        for ext in schemas.values():
            if core_schema_uri == ext:
                continue
            schemas = merge_schemas(schemas, ext)

        # Add custom schemas
        custom_schemas = pq.get_custom_schemas()
        schemas = merge_schemas(schemas, custom_schemas)

        parquet_schema = pq.get_parquet_schema()
        # Check that all required fields are present
        for key in schemas.get("required", []):
            if key not in parquet_schema.names:
                self.error(f"{key}: Required field is missing")
                valid = False

        # Validate whether the Parquet schema complies with the property schemas
        geo = pq.get_geo_metadata()
        properties = schemas.get("properties", {})
        for key in parquet_schema.names:
            # Ignore fields without a schema
            if key not in properties:
                self.warning(f"{key}: No schema defined")
                continue

            prop_schema = properties[key]
            # Make sure the schema has a data type assigned
            dtype = prop_schema.get("type")
            if dtype is None:
                self.warning(f"{key}: No type specified")
                continue

            pq_field = parquet_schema.field(key)
            pq_type = pq_field.type

            # Does the field (dis)allow null?
            nullable = key not in schemas.get("required", [])
            if nullable != pq_field.nullable:
                self.error(
                    f"{key}: Nullability differs, is {pq_field.nullable} but must be {nullable}",
                )
                valid = False

            # Is the data type of the field correct?
            pa_check = PA_TYPE_CHECK.get(dtype)
            if pa_check is None:
                self.warning(f"{key}: Validating {dtype} is not supported yet")
                continue
            elif not pa_check(pq_type):
                self.error(f"{key}: Data type invalid, is {pq_type} but must be {dtype}")
                valid = False
                continue

            # Check specifics of some types
            if dtype == "date-time":
                if pq_type.unit != "ms":
                    self.warning(f"{key}: Timestamp unit differs, should be ms")
                if pq_type.tz != "UTC":
                    self.error(f"{key}: Timestamp timezone invalid, must be UTC")
                    valid = False
            elif dtype == "object":
                if pat.is_map(pq_type) and not pat.is_string(pq_field.key_type):
                    self.error(f"{key}: Map keys must be strings")
                    valid = False
            elif dtype == "geometry":
                valid = self.validate_geometry_column(key, prop_schema, geo, valid)

            # Validate data of the column
            if gdf is not None:
                issues = self.validate_column(gdf[key], prop_schema)
                if len(issues) > 0:
                    for issue in issues:
                        self.info(f"{key}: {issue}")
                    valid = False

        # Show a note once if data was not validated
        if not config.get("data"):
            self.warning("Data was not validated as the --data parameter was not provided")

        return valid

    def validate_geometry_column(self, key, prop_schema, geo, valid=True):
        columns = geo.get("columns", {})
        if key not in columns:
            self.error(f"{key}: Geometry column not found in GeoParquet metadata")
            valid = False

        schema_geo_types = prop_schema.get("geometryTypes", [])
        schema_geo_types.sort()
        if len(schema_geo_types) > 0:
            gp_geo_types = columns[key].get("geometry_types", [])
            gp_geo_types.sort()
            if len(gp_geo_types) == 0:
                self.warning(f"{key}: No geometry types specified in GeoParquet metadata")

            if schema_geo_types != gp_geo_types:
                self.error(
                    f"{key}: GeoParquet geometry types differ, is {gp_geo_types} but must be {schema_geo_types}",
                )
                valid = False

        return valid

    # todo: use a geoparquet validator instead of our own validation routine
    def validate_geoparquet_schema(self, pq: GeoParquet):
        geo = pq.get_geoparquet_metadata()
        if geo is None:
            self.error("File does not have GeoParquet metadata")
            return False

        try:
            schema = pq.get_geoparquet_schema()
            errors = self.validate_json_schema(geo, schema)
            for error in errors:
                self.error(f"GeoParquet metadata: {error.path}: {error.message}")

            return len(errors) == 0
        except Exception as e:
            self.error(f"Failed to validate GeoParquet metadata due to an internal error: {e}")
            return False

    def validate_json_schema(self, obj, schema):
        if isinstance(obj, (bytearray, bytes, str)):
            obj = json.loads(obj)

        validator = ValidateSchema()
        return validator.validate(obj)
