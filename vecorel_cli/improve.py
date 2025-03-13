from pathlib import Path
from typing import Optional, Union

from geopandas import GeoDataFrame

from .basecommand import BaseCommand
from .const import CORE_COLUMNS
from .parquet.parquet import create_parquet
from .util import (
    is_schema_empty,
    load_parquet_data,
    load_parquet_schema,
    parse_metadata,
    pick_schemas,
)


class ImproveData(BaseCommand):
    cmd_title = "Improve datasets"
    cmd_fn = "improve_file"

    def load(self, inputfile: Union[Path, str]) -> tuple[GeoDataFrame, dict]:
        # Load the dataset
        schema = load_parquet_schema(inputfile)
        collection = parse_metadata(schema, b"fiboa")
        columns = list(schema.names)
        data = load_parquet_data(inputfile, columns=columns)
        return data, collection

    def write(
        self,
        gdf: GeoDataFrame,
        outputfile: Union[Path, str],
        collection: dict = {},
        compression=None,
        geoparquet1=False,
    ):
        if isinstance(outputfile, str):
            outputfile = Path(outputfile)

        outputfile.parent.mkdir(parents=True, exist_ok=True)

        columns = list(gdf.columns)
        # Don't write the bbox column, will be added automatically in create_parquet
        if "bbox" in columns:
            del gdf["bbox"]
            columns.remove("bbox")
        # Write the merged dataset to the output file
        create_parquet(
            gdf,
            columns,
            collection,
            outputfile,
            {},
            compression=compression,
            geoparquet1=geoparquet1,
        )

    def improve_file(
        self, inputfile, outputfile=None, compression=None, geoparquet1=False, **kwargs
    ):
        if not outputfile:
            outputfile = inputfile  # overwrite inputfile

        gdf, collection = self.load(inputfile)
        gdf, collection = self.improve(gdf, collection=collection, **kwargs)
        gdf = self.write(
            gdf, outputfile, collection=collection, compression=compression, geoparquet1=geoparquet1
        )
        self.log(f"Wrote data to {outputfile}", "success")

    def improve(
        self,
        gdf: GeoDataFrame,
        collection: dict = {},
        rename_columns: dict[str, str] = {},
        add_sizes: bool = False,
        fix_geometries: bool = False,
        explode_geometries: bool = False,
        crs: Optional[str] = None,
    ) -> tuple[GeoDataFrame, dict]:
        # Change the CRS
        if crs is not None:
            gdf = self.change_crs(gdf, crs)
            self.log(f"Changed CRS to {crs}", "info")

        # Fix geometries
        if fix_geometries:
            gdf = self.fix_geometries(gdf)
            self.log("Fixed geometries", "info")

        # Convert MultiPolygons to Polygons
        if explode_geometries:
            gdf = self.explode_geometries(gdf)
            self.log("Exploded geometries", "info")

        # Rename columns
        if len(rename_columns) > 0:
            self.rename_warnings(gdf, rename_columns)
            gdf, collection = self.rename_properties(gdf, rename_columns, collection)
            self.log("Renamed columns", "info")

        # Add sizes
        if add_sizes:
            gdf = self.add_sizes(gdf)
            self.log("Computed sizes", "info")

        return gdf, collection

    def change_crs(self, gdf: GeoDataFrame, crs: str) -> GeoDataFrame:
        gdf.to_crs(crs=crs, inplace=True)
        return gdf

    def fix_geometries(self, gdf: GeoDataFrame) -> GeoDataFrame:
        gdf.geometry = gdf.geometry.make_valid()
        return gdf

    def explode_geometries(self, gdf: GeoDataFrame) -> GeoDataFrame:
        """
        Explode the geometries in the GeoDataFrame.
        """
        return gdf.explode()

    def rename_warnings(self, gdf: GeoDataFrame, rename: dict) -> None:
        """
        Print warnings for columns that will be renamed.
        """
        # todo: load CORE_COLUMNS from schema
        for col in rename:
            if col in CORE_COLUMNS:
                self.log(
                    f"Column {col} is a core property - do you really want to rename it?",
                    "warning",
                )
            if ":" in col:
                self.log(
                    f"Column {col} might be an extension property - do you really want to rename it?",
                    "warning",
                )

    def rename_properties(
        self, gdf: GeoDataFrame, rename: dict, collection: dict = {}
    ) -> tuple[GeoDataFrame, dict]:
        """
        Rename properties (columns) in the GeoDataFrame according to the provided mapping.

        This method works in-place and modifies the original GeoDataFrame.
        """
        columns = list(gdf.columns)

        gdf.rename(columns=rename, inplace=True)

        custom_schemas = collection.get("custom_schemas", {})
        custom_schemas = pick_schemas(custom_schemas, columns, rename)
        if not is_schema_empty(custom_schemas):
            collection["custom_schemas"] = custom_schemas

        return gdf, collection

    # todo: move to fiboa CLI?
    def add_sizes(self, gdf: GeoDataFrame) -> GeoDataFrame:
        """
        Add area and perimeter columns to the GeoDataFrame.

        This method works in-place and modifies the original GeoDataFrame.
        """
        # Add the area and perimeter columns
        for name in ["area", "perimeter"]:
            if name not in gdf.columns:
                # Create column if not present
                gdf[name] = None

        gdf_m = gdf
        # Determine whether the given CRS is in meters
        if gdf.crs.axis_info[0].unit_name not in ["m", "metre", "meter"]:
            # Reproject the geometries to an equal-area projection if needed
            gdf_m = gdf.to_crs("EPSG:6933")

        # Compute the missing area and perimeter values
        gdf["area"] = gdf_m["area"].astype("float").fillna(gdf_m.geometry.area * 0.0001)
        gdf["perimeter"] = gdf_m["perimeter"].astype("float").fillna(gdf_m.geometry.length)

        return gdf
