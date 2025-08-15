import pathlib

import click
from yarl import URL

from ..vecorel.util import get_fs, is_url

IGNORE_FILES = ["collection.json", "catalog.json"]  # likely STAC


class PathOrURL(click.ParamType):
    name = "path_or_url"

    @staticmethod
    def flatten_tuples(ctx, param, value) -> list:
        if not value:
            return []
        data = []
        for v in value:
            if isinstance(v, tuple) or isinstance(v, list):
                data.extend(v)
            else:
                data.append(v)
        return data

    def __init__(self, *, multiple: bool = False, extensions: list[str] = []):
        self.extensions = extensions
        self.multiple = multiple
        self.path_type = click.Path(
            exists=True,
            dir_okay=multiple,
            resolve_path=True,
            allow_dash=False,
            path_type=pathlib.Path,
        )

    def convert(self, value, param, ctx):
        # Check if it's a URL
        if "://" in value and is_url(value):
            fs = get_fs(value)
            if fs.exists(value):
                return URL(value)
            else:
                self.fail(
                    f"URL '{value}' is does not exist or is currently unavailable.", param, ctx
                )

        # Otherwise, validate as a local path
        filepath = self.path_type.convert(value, param, ctx)
        if filepath.is_dir():
            files = []
            for f in filepath.iterdir():
                if not self._check_extension(f):
                    continue
                if f.name in IGNORE_FILES:
                    continue

                files.append(f)
            return tuple(files)
        elif not self._check_extension(filepath):
            self.fail(
                f"File '{filepath}' must have one of the following extensions: {', '.join(self.extensions)}",
                param,
                ctx,
            )
        return filepath

    def _check_extension(self, filepath: pathlib.Path) -> bool:
        return len(self.extensions) == 0 or filepath.suffix.lower() in self.extensions

    def shell_complete(self, ctx, param, incomplete):
        if "://" in incomplete:
            return []
        return super().shell_complete(ctx, param, incomplete)
