from typing import Optional

import click
from geopandas import GeoDataFrame

from .basecommand import BaseCommand, runnable
from .cli.options import CRS, GEOPARQUET_COMPRESSION, GEOPARQUET_VERSION
from .cli.util import parse_map, valid_vecorel_file
from .encoding.auto import create_encoding
from .jsonschema.util import (
    is_schema_empty,
    pick_schemas,
)
from .registry import Registry


class ImproveData(BaseCommand):
    cmd_name = "improve"
    cmd_title = "Improve datasets"
    cmd_help = (
        "'Improves' a Vecorel file (GeoParquet or GeoJSON) according to the given parameters."
    )
    cmd_final_report = True

    @staticmethod
    def get_cli_args():
        return {
            "input": click.argument(
                "input",
                nargs=1,
                callback=valid_vecorel_file,
            ),
            "out": click.option(
                "--out",
                "-o",
                type=click.Path(exists=False),
                help="Path to write to. If not given, overwrites the input file.",
                default=None,
            ),
            "rename": click.option(
                "--rename",
                "-r",
                type=click.STRING,
                callback=lambda ctx, param, value: parse_map(value),
                multiple=True,
                help="Renaming of properties/columns. Provide the old name and the new name separated by an equal sign. Can be used multiple times.",
            ),
            "add-sizes": click.option(
                "--add-sizes",
                "-sz",
                is_flag=True,
                type=click.BOOL,
                help="Computes missing sizes (area, perimeter)",
                default=False,
            ),
            "fix-geometries": click.option(
                "--fix-geometries",
                "-g",
                is_flag=True,
                type=click.BOOL,
                help="Tries to fix invalid geometries that are repored by the validator (uses GeoPanda's make_valid method internally)",
                default=False,
            ),
            "explode-geometries": click.option(
                "--explode-geometries",
                "-e",
                is_flag=True,
                type=click.BOOL,
                help="Converts MultiPolygons to Polygons",
                default=False,
            ),
            "crs": CRS(None),
            "compression": GEOPARQUET_COMPRESSION,
            "geoparquet_version": GEOPARQUET_VERSION,
        }

    @runnable
    def improve_file(self, input, out=None, compression=None, geoparquet_version=None, **kwargs):
        input_encoding = create_encoding(input)
        output_encoding = create_encoding(out) if out else input_encoding

        geodata = input_encoding.read()
        collection = input_encoding.get_collection()
        geodata, collection = self.improve(geodata, collection=collection, **kwargs)
        output_encoding.write(
            geodata,
            collection=collection,
            compression=compression,
            geoparquet_version=geoparquet_version,
        )
        return out

    def improve(
        self,
        gdf: GeoDataFrame,
        collection: dict = {},
        rename: dict[str, str] = {},
        add_sizes: bool = False,
        fix_geometries: bool = False,
        explode_geometries: bool = False,
        crs: Optional[str] = None,
    ) -> tuple[GeoDataFrame, dict]:
        # Change the CRS
        if crs is not None:
            gdf = self.change_crs(gdf, crs)
            self.info(f"Changed CRS to {crs}")

        # Fix geometries
        if fix_geometries:
            gdf = self.fix_geometries(gdf)
            self.info("Fixed geometries")

        # Convert MultiPolygons to Polygons
        if explode_geometries:
            gdf = self.explode_geometries(gdf)
            self.info("Exploded geometries")

        # Rename columns
        if len(rename) > 0:
            self.rename_warnings(gdf, rename)
            gdf, collection = self.rename_properties(gdf, rename, collection)
            self.info("Renamed columns")

        # Add sizes
        if add_sizes:
            gdf = self.add_sizes(gdf)
            self.info("Computed sizes")

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
        for col in rename:
            if col in Registry.core_columns:
                self.warning(f"Column {col} is a core property - do you really want to rename it?")
            if ":" in col:
                self.warning(
                    f"Column {col} might be an extension property - do you really want to rename it?"
                )

    def rename_properties(
        self, gdf: GeoDataFrame, rename: dict, collection: dict = {}
    ) -> tuple[GeoDataFrame, dict]:
        """
        Rename properties (columns) in the GeoDataFrame according to the provided mapping.

        This method works in-place and modifies the original GeoDataFrame.
        """
        # todo: check whether this handles extensions correctly
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

        # todo: add extension schema for the area and perimeter property
        # Compute the missing area and perimeter values
        gdf["area"] = gdf_m["area"].astype("float").fillna(gdf_m.geometry.area * 0.0001)
        gdf["perimeter"] = gdf_m["perimeter"].astype("float").fillna(gdf_m.geometry.length)

        return gdf
