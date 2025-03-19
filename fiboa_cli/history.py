import os

from .const import CORE_COLUMNS
from .parquet import create_parquet
from .util import (
    is_schema_empty,
    load_parquet_data,
    load_parquet_schema,
    log,
    parse_metadata,
    pick_schemas,
)
import re

COLUMNS =  ("crop:code", "crop:name", "crop:name_en", "ec:hcat_name", "ec:hcat_code", "ec:translated_name")

def history(
    input,
    out=None,
    column_filter=None,
    compression=None,
):
    # alternatively, lookup from determination_datetime (does not work in all cases
    year_index = {int(re.search(r"\d{4}", i).group(0)): index for index, i in enumerate(input)}
    assert len(year_index) == len(input), "Different input files with same year not implemented"
    newest_index = list(year_index).index(max(year_index))
    newest_file = input[newest_index]
    if not out:
        out = newest_file.replace(".parquet", "_hist.parquet")
    else:
        directory = os.path.dirname(out)
        if directory:
            os.makedirs(directory, exist_ok=True)

    # Load the dataset
    schemas = [load_parquet_schema(i) for i in input]
    collections = [parse_metadata(schema, b"fiboa") for schema in schemas]

    gdf = load_parquet_data(newest_file)
    columns = list(schemas[newest_index].names)
    for year, index in year_index.items():
        if index == newest_index:
            continue
        add_columns = [name for name in schemas[index].names if name in (column_filter or COLUMNS)]
        path = input[index]
        if len(add_columns) == 0:
            log("No columns added for file {path} year {year}", "warning")
            continue
        new_columns = [f"{year}:{c}" for c in add_columns]

        gdf2 = load_parquet_data(path, columns=add_columns + [gdf.active_geometry_name])
        overlap = gdf[["id", "geometry"]].overlay(gdf2, how='intersection')

        if gdf.crs.axis_info[0].unit_name not in ["m", "metre", "meter"]:
            overlap = overlap.to_crs("EPSG:6933")
        overlap["area"] = overlap.geometry.area * 0.0001

        overlap.groupby(["id_1"])
        # TODO,
        # group by id_1, look for max(crop:name, key=area), and add this as a column to gdf
        # Start debugging here!

    # Write the merged dataset to the output file
    # TODO, create proper collection
    collection = collections[1]

    create_parquet(
        gdf, columns, collection, out, {}, compression=compression
    )
    log(f"Wrote data to {out}", "success")
