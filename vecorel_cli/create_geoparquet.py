from .parquet.parquet import create_parquet
from .util import collection_from_featurecollection, load_file, log


def create_geoparquet(files, output_file, schemas):
    # Load all features from the GeoJSON files
    features = []
    geojson = {}
    file = None
    collection = {}
    for file in files:
        geojson = load_file(file)
        if geojson["type"] == "Feature":
            features.append(geojson)
        elif geojson["type"] == "FeatureCollection":
            features += geojson["features"]
            collection = collection_from_featurecollection(geojson)
        else:
            log(f"{file}: Skipped - Unsupported GeoJSON type, must be Feature or FeatureCollection")

    if len(features) == 0:
        raise Exception("No valid features provided as input files")

    # Get a list of the properties/columns (without duplicates)
    columns = set(["id", "geometry"])
    for feature in features:
        keys = feature["properties"].keys()
        columns.update(keys)

    columns = list(columns)
    columns.sort()

    # Create the Parquet file
    create_parquet(features, columns, collection, output_file, config={"schemas": schemas})
    log(f"Wrote to {output_file}", "success")
