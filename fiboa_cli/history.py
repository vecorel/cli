import os
from .parquet import create_parquet
from .util import (
    load_parquet_data,
    load_parquet_schema,
    log,
    parse_metadata,
)
import re
import pandas as pd
import numpy as np

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
    # TODO how to handle non-unique ids, maybe generate an additional "_a"
    # https://stackoverflow.com/a/26601343/193886
    gdf.drop_duplicates('id', inplace=True)

    # gdf[gdf.index.duplicated()].sort_values(by='id)
    gdf.set_index("id", drop=False, inplace=True)
    columns = list(schemas[newest_index].names)
    for year, index in year_index.items():
        if index == newest_index:
            continue
        add_columns = [name for name in schemas[index].names if name in (column_filter or COLUMNS)]
        path = input[index]
        if len(add_columns) == 0:
            log("No columns added for file {path} year {year}", "warning")
            continue

        gdf2 = load_parquet_data(path, columns=add_columns + [gdf.active_geometry_name], nrows=1000)
        overlap = gdf[["id", "geometry"]].overlay(gdf2, how='intersection', keep_geom_type=False)

        if gdf.crs.axis_info[0].unit_name not in ["m", "metre", "meter"]:
            overlap = overlap.to_crs("EPSG:6933")
        overlap["area"] = overlap.geometry.area * 0.0001

        # largest_overlap = overlap.groupby(["id_1"])['area'].nlargest(1)

        groupby = ["id", *add_columns]
        subset = overlap[groupby + ["area"]]
        area_per_group = subset.groupby(groupby, as_index=False).sum("area")
        # largest_overlap = area_per_group.groupby(groupby, as_index=False)['area'].nlargest(1)

        largest_overlap = area_per_group.loc[area_per_group.groupby("id")["area"].idxmax()]
        largest_overlap.set_index("id", inplace=True)

        # largest_overlap = area_per_group.groupby("id", as_index=False)[['area', 'crop:code', 'crop:name']][0]
        # Use same index https://stackoverflow.com/a/72932903/193886
        largest_overlap[str(year)] = largest_overlap[add_columns].to_dict("records")
        gdf = gdf.assign(**{str(year): largest_overlap[str(year)]})
        breakpoint()

        # largest_overlap.loc["105449105.0"]
        # gdf.loc[gdf["id"]==largest_overlap["id"]]["history"] = 10
        # https://stackoverflow.com/a/70991362/193886
        # gdf['history'] = np.where(gdf['id'].reset_index(drop=True) == largest_overlap['id'].reset_index(drop=True), largest_overlap['crop:name'], None)

        # pd.merge(gdf, largest_overlap, on="id")


    # Write the merged dataset to the output file
    # TODO, create proper collection
    collection = collections[1]

    create_parquet(
        gdf, columns, collection, out, {}, compression=compression
    )
    log(f"Wrote data to {out}", "success")
