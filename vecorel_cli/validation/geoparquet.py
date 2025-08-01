from typing import Optional

import pyarrow.types as pat

from ..encoding.geoparquet import GeoParquet
from ..jsonschema.util import merge_schemas
from ..parquet.types import PA_TYPE_CHECK
from ..vecorel.typing import SchemaMapping
from .base import Validator
from .data import validate_column


class GeoParquetValidator(Validator):
    def __init__(self, encoding: GeoParquet):
        super().__init__(encoding)

    def _validate(self, num: Optional[int] = None, schema_map: SchemaMapping = {}):
        # Load data
        try:
            data = self.encoding.read(num=num, hydrate=True)
        except Exception as e:
            return self.error(e)

        # Validate GeoParquet metadata
        if not self.validate_geoparquet_schema(self.encoding):
            return

        # Validate collection metadata in Parquet header
        collection = self.encoding.get_collection()
        if not collection:
            self.error("Collection metadata is missing in Parquet header")
            return

        # Validate schema listings
        schemas = self.encoding.get_schemas()
        loaded_schemas = self.validate_schemas(schemas, schema_map)

        # Merge all core and extension schemas
        schema = {}
        for ext in loaded_schemas.values():
            schema = merge_schemas(schema, ext)

        # Add custom schemas
        custom_schemas = self.encoding.get_custom_schemas()
        schema = merge_schemas(schema, custom_schemas)

        properties = self.encoding.get_properties()
        # Check that all required fields are present
        for key in schema.get("required", []):
            if key not in properties:
                self.error(f"{key}: Required field is missing")

        # Validate whether the Parquet schema complies with the property schemas
        geo = self.encoding.get_geoparquet_metadata()
        property_schemas = schema.get("properties", {})
        parquet_schema = self.encoding.get_parquet_schema().to_arrow_schema()
        for key in properties:
            # Ignore fields without a schema
            if key not in property_schemas:
                self.warning(f"{key}: No schema defined")
                continue

            prop_schema = property_schemas[key]
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
            if data is not None:
                issues = validate_column(data[key], prop_schema)
                if len(issues) > 0:
                    for issue in issues:
                        self.info(f"{key}: {issue}")
                    valid = False

        # Show a note once if data was not validated
        if data is None or data < 1:
            self.warning("Data was not validated, only structural checks were applied")

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
