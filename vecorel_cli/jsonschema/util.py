def is_schema_empty(schema):
    return len(schema.get("properties", {})) == 0 and len(schema.get("required", {})) == 0


def merge_schemas(*schemas):
    """Merge multiple schemas into one"""
    result = {"required": [], "properties": {}}
    for schema in schemas:
        schema = migrate_schema(schema)
        result["required"] += schema.get("required", [])
        result["properties"].update(schema.get("properties", {}))

    return result


def pick_schemas(schema, property_names, rename={}):
    """Pick and rename schemas for specific properties"""
    result = {"required": [], "properties": {}}
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    for prop in property_names:
        prop2 = rename[prop] if prop in rename else prop
        if prop in required:
            result["required"].append(prop2)
        if prop in properties:
            result["properties"][prop2] = properties[prop]

    return result


def migrate_schema(schema):
    """Migrate schema to a new version"""
    return schema.copy()
