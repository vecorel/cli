from typing import Optional

import pyarrow.types as pat

from ..encoding.geoparquet import GeoParquet
from ..parquet.types import PA_TYPE_CHECK
from ..vecorel.typing import SchemaMapping
from .base import Validator
from .data import validate_column


class GeoParquetValidator(Validator):
    def __init__(self, encoding: GeoParquet):
        super().__init__(encoding)

    def _validate(self, num: Optional[int] = None, schema_map: SchemaMapping = {}):
        validate_data = num is None or num > 0

        # Load data
        try:
            data = self.encoding.read(num=num, schema_map=schema_map, hydrate=True)
        except Exception as e:
            return self.error(e)

        # Validate GeoParquet metadata
        if not self.validate_geoparquet_schema(self.encoding):
            return

        # Check collection metadata that should be in the Parquet header
        collection = self.encoding.get_collection()
        if collection.is_empty():
            return self.error("Collection metadata is missing in Parquet header")

        # Validate schema lists
        schemas = collection.get_schemas()
        self.validate_schemas(schemas)
        has_multiple_collections = len(schemas) > 1

        # Resolve schemas
        schema = collection.merge_schemas(
            schema_map=schema_map,
            validator=self,
        )

        # Check that all required fields are present
        columns = data.columns
        required_props = schema.get("required", [])
        collection_props = schema.get("collection", {})
        for key in required_props:
            if key not in columns and not collection_props.get(key, False):
                self.error(f"{key}: Required field is missing")

        # Validate whether the Parquet schema complies with the property schemas
        geo = self.encoding.get_geoparquet_metadata()
        property_schemas = schema.get("properties", {})
        parquet_schema = self.encoding.get_parquet_schema().to_arrow_schema()
        properties = self.encoding.get_properties()
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
            nullable = key not in schema.get("required", [])
            if not has_multiple_collections and nullable != pq_field.nullable:
                self.error(
                    f"{key}: Nullability differs, is {pq_field.nullable} but must be {nullable}",
                )

            # Is the data type of the field correct?
            pa_check = PA_TYPE_CHECK.get(dtype)
            if pa_check is None:
                self.warning(f"{key}: Validating {dtype} is not supported yet")
                continue
            elif not pa_check(pq_type):
                self.error(f"{key}: Data type invalid, is {pq_type} but must be {dtype}")
                continue

            # Check specifics of some types
            if dtype == "date-time":
                if pq_type.unit != "ms":
                    self.warning(f"{key}: Timestamp unit differs, should be ms")
                if pq_type.tz != "UTC":
                    self.error(f"{key}: Timestamp timezone invalid, must be UTC")
            elif dtype == "object":
                if pat.is_map(pq_type) and not pat.is_string(pq_field.key_type):
                    self.error(f"{key}: Map keys must be strings")
            elif dtype == "geometry":
                self.validate_geometry_column(key, prop_schema, geo)

            # Validate data of the column
            issues = []
            if validate_data and not has_multiple_collections:
                issues = validate_column(data[key], prop_schema)
            elif validate_data and has_multiple_collections:
                # Validate data for each collection separately
                for cid, cschema in schemas.items():
                    vecorel_schema = cschema.merge_schemas(
                        schema_map=schema_map,
                        custom_schemas=collection.get_custom_schemas(),
                        validator=self,
                    )
                    sub_prop_schema = vecorel_schema.get("properties", {}).get(key, {})
                    sub_data = data[data["collection"] == cid]
                    sub_issues = validate_column(sub_data[key], sub_prop_schema)
                    issues.extend(sub_issues)

            for issue in issues:
                self.error(f"{key}: {issue}")

        # Show a note once if data was not validated
        if not validate_data:
            self.warning("Data was not validated, only structural checks were applied")
        if (
            validate_data
            and num is not None
            and num < self.encoding.get_parquet_metadata().num_rows
        ):
            self.warning(
                f"Data was not fully validated, only the first {num} rows were checked",
            )

    def validate_geometry_column(self, key, prop_schema, geo):
        columns = geo.get("columns", {})
        if key not in columns:
            self.error(f"{key}: Geometry column not found in GeoParquet metadata")

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
