from pathlib import Path
from typing import Any, Dict

type SchemaMapping = Dict[str, Path]

# tood: use proper GeoJSON types?
type FeatureCollection = Dict[str, Any]
type Feature = Dict[str, Any]
