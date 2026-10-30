import os
from tempfile import TemporaryDirectory

from .duckdb import DuckDBBaseConverter


class PerFileConverterMixin:
    """Converts each source on its own and merges the parts, for sources that do not fit
    into memory together. The ids must be unique across the sources, and the parts need
    about the size of the output in free disk space next to it."""

    _part_urls = None

    def get_input_urls(self, input_files=None):
        if self._part_urls is not None:
            return self._part_urls
        return super().get_input_urls(input_files)

    def convert(self, output_file, cache=None, input_files=None, variant=None, **kwargs) -> str:
        self.select_variant(variant)
        urls = self.get_input_urls(input_files)
        # the variant is passed on as selected, so that its default is not reported per part
        try:
            if isinstance(urls, str) or len(urls) <= 1:
                self._part_urls = urls
                return super().convert(output_file, cache=cache, variant=self.variant, **kwargs)

            directory = os.path.dirname(output_file) or "."
            os.makedirs(directory, exist_ok=True)
            with TemporaryDirectory(dir=directory) as parts_folder:
                parts = []
                for index, (uri, target) in enumerate(urls.items()):
                    self.info(f"Converting source {index + 1}/{len(urls)}: {uri}")
                    part = os.path.join(parts_folder, f"part_{index}.parquet")
                    self._part_urls = {uri: target}
                    super().convert(part, cache=cache, variant=self.variant, **kwargs)
                    parts.append(part)

                self.info(f"Merging {len(parts)} parts into {output_file}")
                merge_options = ("compression", "compression_level", "geoparquet_version")
                return DuckDBBaseConverter().merge_parquet(
                    parts, output_file, **{k: kwargs[k] for k in merge_options if k in kwargs}
                )
        finally:
            self._part_urls = None
