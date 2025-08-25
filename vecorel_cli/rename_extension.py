import re
from pathlib import Path
from typing import Optional

import click

from .basecommand import BaseCommand, runnable
from .create_geoparquet import CreateGeoParquet
from .vecorel.typing import SchemaMapping


class RenameExtension(BaseCommand):
    cmd_name = "rename-extension"
    cmd_title = "Prepare extensions"
    cmd_help = "Updates placeholders in an extension folder to the new name."
    cmd_final_report = True

    readme_path: str = "README.md"
    changelog_path: Optional[str] = "CHANGELOG.md"
    pipfile_path: Optional[str] = "Pipfile"
    geojson_example_paths: list[str] = ["examples/geojson/example.json"]
    geoparquet_example_path: Optional[str] = "examples/geoparquet/example.parquet"
    schema_path: str = "schema/schema.yaml"

    template_title: str = "Template"
    template_prefix: str = "template"
    template_org: str = "vecorel"
    template_repo: str = "extension-template"
    template_domain: str = "vecorel.org"

    @staticmethod
    def get_cli_args():
        return {
            "folder": click.argument(
                "folder",
                nargs=1,
                type=click.Path(exists=True, file_okay=False, resolve_path=True, path_type=Path),
            ),
            "title": click.option(
                "--title",
                "-t",
                type=click.STRING,
                help="Title of the extension, e.g. `Timestamps`",
                required=True,
            ),
            "slug": click.option(
                "--slug",
                "-s",
                type=click.STRING,
                help="Slug of the repository, e.g. for `https://github.com/vecorel/xyz-extension` it would be `xyz-extension`",
                required=True,
            ),
            "org": click.option(
                "--org",
                "-o",
                type=click.STRING,
                help="Slug of the organization, e.g. for `https://github.com/vecorel/xyz-extension` it would be `vecorel`",
                show_default=True,
                default=RenameExtension.template_org,
            ),
            "prefix": click.option(
                "--prefix",
                "-p",
                type=click.STRING,
                help="Prefix for the field, e.g. `time` if the fields should be `time:created` or `time:updated`. An empty string removes the prefix, not providing a prefix leaves it as is.",
                default=None,
            ),
        }

    @staticmethod
    def get_cli_callback(cmd):
        def callback(folder, title, slug, org, prefix):
            return RenameExtension(title, slug, org, prefix).run(folder=folder)

        return callback

    def __init__(
        self,
        title: Optional[str] = None,
        repo: Optional[str] = None,
        org: Optional[str] = None,
        prefix: str = None,
    ) -> str:
        self.title: str = title or self.template_title

        self.org: str = org or self.template_org
        self.gh_host: str = self._get_gh_host(self.org)
        self.repo: str = repo or self.template_repo

        self.prefix: str = prefix if prefix is not None else self.template_prefix
        self.full_prefix: str = f"{self.prefix}:" if len(self.prefix) > 0 else ""

        self.url_map: dict[str, str] = {
            f"{self.template_domain}/{self.template_repo}": f"{self.gh_host}/{self.repo}",
            f"github.com/{self.template_org}/{self.template_repo}": f"github.com/{self.org}/{self.repo}",
        }

    def _get_gh_host(self, org):
        return f"{org}.github.io" if org != self.template_org else self.template_domain

    def _get_urls(self):
        search = list(self.url_map.keys())
        replace = list(self.url_map.values())
        return search, replace

    @runnable
    def rename(self, folder):
        p = Path(folder)
        if not p.exists():
            raise ValueError(f"Folder '{p.absolute()}' does not exist")

        self.rename_readme(p)
        self.rename_schema(p)
        if self.changelog_path:
            self.rename_changelog(p)
        if self.pipfile_path:
            self.rename_pipfile(p)

        geojson_paths = [Path(p, geojson_path) for geojson_path in self.geojson_example_paths]
        for geojson_path in geojson_paths:
            self.rename_geojson_example(geojson_path)
        if self.geoparquet_example_path:
            self.rename_geoparquet_example(p, geojson_paths)

    def rename_schema(self, folder: Path) -> bool:
        filepath = Path(folder, self.schema_path)
        return self._replace_in_file(filepath, f"{self.template_prefix}:", self.full_prefix)

    def rename_pipfile(self, folder: Path) -> bool:
        filepath = Path(folder, self.pipfile_path)
        search, replace = self._get_urls()
        return self._replace_in_file(filepath, search, replace)

    def rename_changelog(self, folder: Path) -> bool:
        filepath = Path(folder, self.changelog_path)
        search, replace = self._get_urls()
        return self._replace_in_file(filepath, search, replace)

    def rename_readme(self, folder: Path) -> bool:
        filepath = Path(folder, self.readme_path)
        search, replace = self._get_urls()
        search += [
            f"{self.template_title} Extension",
            f"- **Title:** {self.template_title}",
            f"- **Property Name Prefix:** {self.template_prefix}",
            f"| {self.template_prefix}:",
        ]
        replace += [
            f"{self.title} Extension",
            f"- **Title:** {self.title}",
            f"- **Property Name Prefix:** {self.prefix}",
            f"| {self.full_prefix}",
        ]
        return self._replace_in_file(filepath, search, replace)

    def rename_geojson_example(self, filepath: Path) -> bool:
        search, replace = self._get_urls()
        search += [f"{self.template_prefix}:"]
        replace += [self.full_prefix]
        return self._replace_in_file(filepath, search, replace)

    def _create_geoparquet_command(self) -> CreateGeoParquet:
        return CreateGeoParquet()

    def rename_geoparquet_example(self, folder: Path, geojson_paths: list[str] = []) -> bool:
        filepath = Path(folder, self.geoparquet_example_path)
        schemapath = Path(folder, self.schema_path)
        if filepath.exists():
            filepath.unlink()

        if len(geojson_paths) == 0:
            self.warning(f"Deleted {filepath}")
            return False

        search, replace = self._get_urls()
        schema_url = self._replace_in_str(
            f"https://{self.template_domain}/{self.template_repo}/v0.1.0/schema.yaml",
            search,
            replace,
        )
        schema_map: SchemaMapping = {schema_url: schemapath.absolute()}
        gp = self._create_geoparquet_command()
        gp.create(geojson_paths, filepath, schema_map=schema_map)
        self.success(f"Updated {filepath}")
        return True

    def _replace_in_str(self, content, search, replace):
        if isinstance(search, list) and isinstance(replace, list) and len(search) != len(replace):
            raise ValueError("Search and replace lists must have the same length")

        if isinstance(search, str):
            return content.replace(search, replace)
        elif isinstance(search, re.Pattern):
            return content.replace(search, replace)
        elif isinstance(search, list) and isinstance(replace, list):
            for s, r in zip(search, replace):
                content = self._replace_in_str(content, s, r)
            return content
        elif isinstance(search, list):
            for s in search:
                content = self._replace_in_str(content, s, replace)
            return content
        else:
            raise ValueError(f"Invalid search type: {type(search)}")

    def _replace_in_file(self, file: Path, search, replace) -> bool:
        try:
            with file.open("r+") as f:
                content = f.read()
                content = self._replace_in_str(content, search, replace)
                f.seek(0)
                f.write(content)
                f.truncate()
            self.success(f"Updated {file}")
            return True
        except Exception as e:
            self.error(f"Can't update {file}: {e}")
            return False
