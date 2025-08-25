import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import click
import pandas as pd
from geopandas import GeoDataFrame, GeoSeries
from shapely.geometry import box
from yarl import URL

from .basecommand import BaseCommand, runnable
from .cli.options import JSON_INDENT, VECOREL_FILE_ARG, VECOREL_TARGET_CONSOLE
from .encoding.auto import create_encoding
from .registry import Registry
from .vecorel.collection import Collection
from .vecorel.util import to_iso8601


class CreateStacCollection(BaseCommand):
    cmd_name = "create-stac-collection"
    cmd_title = "Create STAC Collection"
    cmd_help = f"Creates a STAC Collection for {Registry.project} files."
    cmd_final_report = True

    processing_extension = "https://stac-extensions.github.io/processing/v1.1.0/schema.json"
    table_extension = "https://stac-extensions.github.io/table/v1.2.0/schema.json"

    temporal_property = "determination_datetime"

    @staticmethod
    def get_cli_args():
        return {
            "source": VECOREL_FILE_ARG,
            "target": VECOREL_TARGET_CONSOLE,
            "indent": JSON_INDENT,
            "temporal": click.option(
                "temporal_property",
                "--temporal",
                "-t",
                type=click.STRING,
                help="The temporal property to use for the temporal extent.",
                show_default=True,
                default=CreateStacCollection.temporal_property,
            ),
            # todo: allow additional parameters for missing data in the collection?
            # https://stackoverflow.com/questions/36513706/python-click-pass-unspecified-number-of-kwargs
        }

    @runnable
    def create_cli(
        self,
        source: Union[Path, URL, str],
        target: Optional[Union[str, Path]] = None,
        temporal_property: Optional[str] = None,
        indent: Optional[int] = None,
    ) -> Union[Path, str, bool]:
        stac = self.create_from_file(source, data_url=source, temporal_property=temporal_property)
        if stac:
            return self._json_dump_cli(stac, target, indent)
        else:
            return False

    def create_from_file(
        self,
        source: Union[Path, URL, str],
        data_url: str,
        temporal_property: Optional[str] = None,
    ) -> dict:
        if isinstance(source, str):
            source = Path(source)

        # Read source data
        source_encoding = create_encoding(source)
        properties = source_encoding.get_properties().keys()
        required_properties = properties & {"geometry", temporal_property}
        data = source_encoding.read(properties=list(required_properties))
        collection = source_encoding.get_collection()

        # Create STAC collection
        stac = self.create(
            collection,
            data,
            data_url,
            media_type=source_encoding.media_type,
            temporal_property=temporal_property,
        )

        # Add more asset details
        properties = source_encoding.get_properties()
        table_columns = []
        for column, types in properties.items():
            if "null" in types:
                types.remove("null")
            table_columns.append({"name": column, "type": types[0]})

        stac["stac_extensions"].append(self.table_extension)
        asset = stac["assets"]["data"]
        asset["table:columns"] = table_columns
        asset["table:primary_geometry"] = "geometry"
        asset["table:row_count"] = len(data)

        return stac

    def create(
        self,
        collection: Collection,
        gdf: GeoDataFrame,
        data_url: Union[Path, URL, str],
        media_type: Optional[str] = None,
        temporal_property: Optional[str] = None,
    ) -> dict:
        """
        Creates a collection for the field boundary datasets.
        """
        if len(gdf) == 0:
            raise Exception("No data available.")

        id = collection.get("collection")
        if id is None:
            raise Exception(
                "Collection ID not found in collection. Can only create STAC for files containing a single collection."
            )

        title = collection.get("title", id)
        if title is None:
            self.warning("Title is not found in collection, using ID as title.")

        description = collection.get("description", "").strip()
        if len(description) == 0:
            raise Exception("Description is not found in collection.")

        bbox = list(GeoSeries([box(*gdf.total_bounds)], crs=gdf.crs).to_crs(epsg=4326).total_bounds)

        if isinstance(data_url, Path):
            href = "file://" + str(data_url.resolve()).replace("\\", "/")
        else:
            href = str(data_url)
        stac = {
            "stac_version": "1.1.0",
            "stac_extensions": [
                self.processing_extension,
            ],
            "type": "Collection",
            "id": id,
            "title": title,
            "description": description,
            "license": "other",
            "extent": {
                "spatial": {"bbox": [bbox]},
                "temporal": {"interval": [[None, None]]},
            },
            "assets": {
                "data": {
                    "roles": ["data"],
                    "href": href,
                    "processing:software": {
                        Registry.name: Registry.get_version(),
                    },
                }
            },
            "links": [],
        }

        # Add data media type
        if media_type:
            stac["assets"]["data"]["type"] = media_type

        # Add license handling
        license = collection.get("license", "").strip()
        if license.lower() == "dl-de/by-2-0":
            stac["links"].append(
                {
                    "href": "https://www.govdata.de/dl-de/by-2-0",
                    "title": "Data licence Germany - attribution - Version 2.0",
                    "type": "text/html",
                    "rel": "license",
                }
            )
        elif license.lower() == "dl-de/zero-2-0":
            stac["links"].append(
                {
                    "href": "https://www.govdata.de/dl-de/zero-2-0",
                    "title": "Data licence Germany - Zero - Version 2.0",
                    "type": "text/html",
                    "rel": "license",
                }
            )
        else:
            license_name, license_url = self._parse_link_str(license)
            if license_url is None:
                stac["license"] = license_name
            else:
                stac["links"].append(
                    {
                        "href": license_url,
                        "title": license_name,
                        "rel": "license",
                    }
                )

        # Add provider information
        provider = collection.get("provider", "").strip()
        provider_name, provider_url = self._parse_link_str(provider)
        stac["providers"] = [
            {
                "name": provider_name,
                "roles": ["producer", "licensor"],
            }
        ]
        if provider_url:
            stac["providers"][0]["url"] = provider_url

        # Add temporal extent
        temporal_extent = None
        if temporal_property in gdf.columns:
            dates = pd.to_datetime(gdf[temporal_property])
            min_time = to_iso8601(dates.min())
            max_time = to_iso8601(dates.max())
            temporal_extent = [min_time, max_time]
        elif temporal_property in collection:
            time = to_iso8601(datetime.fromisoformat(collection[temporal_property]))
            temporal_extent = [time, time]
        if temporal_extent is not None:
            stac["extent"]["temporal"]["interval"][0] = temporal_extent

        return stac

    def _parse_link_str(self, link_str: str) -> tuple[str, Optional[str]]:
        """
        Parse a link string into a dictionary.
        The string can be in the format "Name <URL>" or just "Name".
        """
        match = re.match(r"^(.*?)(?:\s*<(.+?)>)?$", link_str.strip())
        if match:
            return match.groups()
        return link_str.strip(), None
