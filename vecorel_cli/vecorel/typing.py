from pathlib import Path
from typing import Any, Dict, TypeAlias, Union

# Only available in Python 3.12+
# type SchemaMapping = Dict[str, Path]
# type RawSchemas = dict[str, list[str]]
# type FeatureCollection = Dict[str, Any]
# type Feature = Dict[str, Any]
# type Sources = Union[str, dict[str, Union[str, list[str]]]]

SchemaMapping: TypeAlias = Dict[str, Path]
RawSchemas: TypeAlias = dict[str, list[str]]
# todo: use proper GeoJSON types?
FeatureCollection: TypeAlias = Dict[str, Any]
Feature: TypeAlias = Dict[str, Any]
Sources: TypeAlias = Union[str, dict[str, Union[str, list[str]]]]
