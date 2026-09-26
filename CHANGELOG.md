# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `vec merge` merges local GeoParquet files that are all in the target CRS with DuckDB,
  without loading them into memory; `--engine` chooses the engine explicitly.
- `vec merge --crs first` keeps the CRS of the first dataset, the default is still EPSG:4326.
- `merge_parquet` accepts `properties` to restrict the merged properties.

### Changed

- **Breaking:** `vec merge` keeps all properties by default, `--include` restricts them to
  the core properties plus the given ones and `--exclude` removes any property. It warns if
  a required property is not included.

### Fixed

- `merge_parquet` no longer drops a property that each part kept as a constant in
  its collection but on which the parts disagree; it becomes a column again, as in
  `vec merge`.
- Merging no longer overwrites the schemas of a collection that occurs in multiple
  datasets, it unites them.
- Merging warns about collection-only properties that differ between the datasets
  and have to be removed.
- Merging fills in missing collection values of datasets that only list a single
  collection in `schemas`.
- Merging hydrates array and object constants correctly, instead of spreading them
  over the rows, dropping them (`vec merge`) or failing (`merge_parquet`).
- `merge_parquet` checks and numbers repeating ids per collection instead of across
  all collections, and checks the required properties per collection.
- `merge_parquet` hydrates date-time, date and binary constants with their types and
  NaN as null.
- `merge_parquet` recomputes the bbox, which was empty for the rows of GeoParquet 1.0 parts.
- Columns without any value are no longer moved to the collection, which wrote NaN
  (invalid JSON) or failed for nullable integers.
- `get_pyarrow_type` no longer modifies the schema of objects with `patternProperties`.
- Validation checks that all features in GeoParquet files have a collection that is
  listed in `schemas`, and the required properties per collection.
- Validation checks the schemas of all collections, not only the first one.
- Validation no longer fails with a `KeyError` for GeoParquet files with multiple
  collections, but without a collection column.
- The in-memory merge keeps constants that all datasets share in the collection, instead
  of failing on or moving array and object constants into the rows.
- `vec merge` with DuckDB keeps rows without a required value (with a warning) and
  rows with an empty geometry, like the in-memory merge.
- `merge_parquet` warns about a constant that doesn't fit the type of its schema.
- Merging rejects two versions of the same schema in one collection.
- `vec merge --exclude` no longer reads datasets other than GeoParquet twice.
- Merging warns when `--include` drops a required collection-only property.
- Merging accepts features again whose collection can't be determined.

## [v0.3.1] - 2026-09-24

### Fixed

- ZIP archives compressed with Deflate64 are extracted through `inflate64` (a
  dependency of py7zr, now declared). They required `zipfile-deflate64`, which was
  not declared and has no wheels for Python 3.11+.

## [v0.3.0] - 2026-09-24

### Added

- `download_files()` now handles multi-volume 7z archives: URIs ending in `.7z.001`,
  `.7z.002`, ... that share a name are downloaded together and extracted as one 7z
  stream, with the target paths read from whichever part carries them (fiboa/cli#312).
- `id_columns` (with `id_separator`, default `-`): composes `id` by joining the
  named columns, after the column migrations ran. Integer-typed float columns are cast
  losslessly, so an id part does not render as `4.0`.
- Conversions report how many geometry parts the geometry repair removed;
  previously they vanished silently (#33).

### Changed

- Conversions no longer drop rows with missing required values: any row without a value
  for a required property fails the conversion, so each dataset handles such rows
  explicitly (#33).
- Converters no longer split multi-part geometries into one row per polygon (#47).
  Features keep the geometry modeling of the source, so ids, row counts and attribute
  values (such as an area) stay 1:1 with it. Rows without a polygonal geometry
  are dropped with a warning. Use `vec improve --explode-geometries` when single polygons
  are needed.
- Converters now guarantee unique ids (#47): ids that repeat — a source without unique
  ids, or rows repeating across merged parts — are numbered with a `~<n>` suffix
  (`id~1`, `id~2`, ...).
- Converters number the rows (over all source files) as `id` when no column is mapped
  to `id`, or when the mapped column is missing from the data (#47). Previously the
  per-file numbering also repeated ids after a multi-file read.
- `vec improve --explode-geometries` numbers the ids of the parts it creates (`~<n>`),
  so the result keeps unique ids.

### Removed

- `max_dropped_share`, as rows with missing required values are no longer dropped (#33).
- The `index_as_id` flag and the `"id": "id"` mapping it required (#47).

### Fixed

- A download that ends before its `Content-Length` is reached now fails instead
  of caching the partial file, which a later run would otherwise reuse as if it were
  complete (#46).

## [v0.2.20] - 2026-09-17

### Changed

- `BaseConverter.convert()` chooses a default variant when none is given, before
  `get_urls()` runs: the latest year when the variants are years, otherwise the first
  declared one (`default_variant()`). A converter that overrides `get_urls()` no longer has
  to repeat the default, and it is also set when the input files are supplied by the user.

## [v0.2.19] - 2026-09-17

### Added

- `DuckDBBaseConverter.merge_parquet()`, which combines Vecorel GeoParquet files
  into one, checked and sorted over the whole set. `convert()` now ends in the same
  `write_query()`, so there is one route from a query to a packaged file (#36).
- `BaseConverter.dehydrate` (default `True`). Set it to `False` when a conversion
  writes one part of a dataset: constants would otherwise be judged over the part and
  a property that varies between parts is lost (#35).

### Changed

- Require `aiohttp>=3.13.5`, which allows downloads from servers that send duplicate
  headers, such as Zenodo (#41).

### Fixed

- A constant pinned to the feature level was passed to DuckDB as a bound parameter,
  which a `COPY` binds before its subquery's, so the output went to a file named after the
  constant.
- An integer column with a null value read back as float64, so validation
  rejected every value in it (#37). Integers are now read into pandas' nullable
  dtypes, which also keeps int64 values that float64 cannot represent exactly.
- A failed download left an empty file in the cache that later runs treated as
  cached, so they never retried and failed with an unrelated error (#43). Downloads now
  stream to a `.part` file that is renamed only after a clean close.

## [v0.2.18] - 2026-09-14

### Added

- An experimental `DuckDBBaseConverter` to convert large Parquet-based datasets
  without loading them into memory. Its output matches the default converter
  (geometry handling, Hilbert order, data types, metadata, file packaging).
  `duckdb` is a new dependency.
- Converters warn when no column is mapped to `id` and when the id column is not unique.

### Changed

- Converters record the collection id in the collection metadata and no longer add a
  constant `collection` column. Previously files without constant columns were written
  without any collection id.
- Converters drop rows that can never validate (missing required values, empty or
  missing geometries). Missing required values are dropped only up to the new
  `max_dropped_share` (default 1%), above it the conversion fails.
- Converters fail when both `sources` and `variants` are declared.
- Converters load all schemas upfront with retries, so a temporary network issue
  no longer kills a long conversion at the very end.
- Send `User-Agent: vecorel-cli` on HTTP downloads instead of fsspec's default. Servers that
  reject the default answer 403, which surfaced as `FileNotFoundError` naming only the URL and
  read as a dead source.

## [v0.2.17] - 2026-09-03

### Fixed

- Read GeoJSON as UTF-8, which the format mandates, instead of following the platform locale.
  The locale default is cp1252 on Windows, where `Grünland` silently became `GrÃ¼nland` — in
  converters, and in `describe`, `merge` and `validate`. Writing now states UTF-8 explicitly too,
  which leaves the output unchanged.
- Accept a byte order mark when reading GeoJSON, instead of failing with
  `JSONDecodeError: Unexpected UTF-8 BOM`. Output still never contains one.

## [v0.2.16] - 2026-08-29

### Changed

- Sort converter output by Hilbert distance against the CRS's total bounds instead of by raw WKB byte order.

### Fixed

- Exit with a non-zero exit code when a command reports a failure (e.g. `vec validate-schema` on an invalid schema) [#27](https://github.com/vecorel/cli/issues/27)
- Keep collection-only properties in the collection metadata when merging collections,
  e.g. in `create-geoparquet` and `merge`.
  Properties are kept if they have the same value in all source collections.
  [#26](https://github.com/vecorel/cli/issues/26)

## [v0.2.15] - 2026-02-16

### Added

- A `get_default_collection` to the Registry

## [v0.2.14] - 2026-02-13

### Added

- Enable verbose mode via env `VECOREL_VERBOSE` set to `1`

### Changed

- Converters: Load the most specific class for converters
- Converters: Made glob recursive, so it can be used for multiple directories

### Fixed

- Converters: Move block size check so that it applies for all downloads
- Converters: Avoid error with license set to None

## [v0.2.13] - 2026-02-13

### Added

- Option to set compression level, zstd defaults to 15
- Support for Python 3.14

### Changed

- Change default compression to zstd
- Replace flatdict from pypi with a local version to avoid pkg_resource install issues
- Updated dependencies (especially catering for future pandas versions)

### Removed

- Support for Python 3.10

## [v0.2.12] - 2025-12-08

### Added

- Enable Converter.columns list and tuple types
- BaseConverter get_columns hook to customize columns after reading the file

### Changed

- Change default temporal property to datetime
- Update STAC processing extension

## [v0.2.11] - 2025-10-09

### Fixed

- XML/HTML-like tags (with < and > characters) in logs are properly escaped for loguru

## [v0.2.10] - 2025-10-09

### Changed

- Set the default temporal_property for STAC collection creation to `determination:datetime` instead of `determination_datetime`

### Fixed

- XML tags in logs are properly escaped for loguru

## [v0.2.9] - 2025-10-09

### Added

- Converters: `column_filters` allows to inverse the mask

### Fixed

- Fix use of license and provider in converter list
- Various small bug fixes and type hint fixes

## [v0.2.8] - 2025-09-13

### Fixed

- Fix issue with schema requests due to changes in the "firewall" by ReadTheDocs that sits in front of the PROJJSON schema

## [v0.2.7] - 2025-08-29

### Changed

- `create-stac-collection`:
  - Don't set empty strings / only provide properties that have value
  - Detect the collection id more robustly

## [v0.2.6] - 2025-08-29

### Changed

- Move ValidateData.required_schemas to Registry.required_extensions and adapted ValidateData accordingly

## [v0.2.5] - 2025-08-29

### Added

- `unrar` dependency
- `create-stac-collection`: Support for GeoJSON input
- Allow to set a list of required schemas for validation

### Fixed

- Fix deprecation warning for `re.sub`
- `create-stac-collection`: Set temporal property parameter from none to the actual configured default

## [v0.2.4] - 2025-08-27

### Changed

- Code refactoring

### Fixed

- Encode numpy datatypes correctly when exporting to JSON

## [v0.2.3] - 2025-08-26

### Changed

- Better support for merging schemas

## [v0.2.2] - 2025-08-25

### Added

- Return value to `ConvertData.check_datasets`

### Changed

- Make the whole library easier to rebrand and reuse

### Fixed

- Separate CLI creation from `__init__.py` files to avoid import race conditions
- Fix geopandas `datetime64` data type conversion issue

## [v0.2.1] - 2025-08-25

### Changed

- Updated to use the Geometry Metrics Extension

### Fixed

- Fixed various hardcoded vecorel instances in rename-extension
- Fixed registry to be overridable by other CLI tools

## [v0.2.0] - 2025-08-15

### Added

- Internal `py-package` parameter to the `convert` command

### Changed

- Migrate from vecorel.github.io to vecorel.org

### Fixed

- Bugfixes

## [v0.1.0] - 2025-08-15

### Added

- First release based on vecorel CLI 0.1.0

[Unreleased]: <https://github.com/vecorel/cli/compare/v0.3.1...main>
[v0.3.1]: <https://github.com/vecorel/cli/compare/v0.3.0...v0.3.1>
[v0.3.0]: <https://github.com/vecorel/cli/compare/v0.2.20...v0.3.0>
[v0.2.20]: <https://github.com/vecorel/cli/compare/v0.2.19...v0.2.20>
[v0.2.19]: <https://github.com/vecorel/cli/compare/v0.2.18...v0.2.19>
[v0.2.18]: <https://github.com/vecorel/cli/compare/v0.2.17...v0.2.18>
[v0.2.17]: <https://github.com/vecorel/cli/compare/v0.2.16...v0.2.17>
[v0.2.16]: <https://github.com/vecorel/cli/compare/v0.2.15...v0.2.16>
[v0.2.15]: <https://github.com/vecorel/cli/compare/v0.2.14...v0.2.15>
[v0.2.14]: <https://github.com/vecorel/cli/compare/v0.2.13...v0.2.14>
[v0.2.13]: <https://github.com/vecorel/cli/compare/v0.2.12...v0.2.13>
[v0.2.12]: <https://github.com/vecorel/cli/compare/v0.2.11...v0.2.12>
[v0.2.11]: <https://github.com/vecorel/cli/compare/v0.2.10...v0.2.11>
[v0.2.10]: <https://github.com/vecorel/cli/compare/v0.2.9...v0.2.10>
[v0.2.9]: <https://github.com/vecorel/cli/compare/v0.2.8...v0.2.9>
[v0.2.8]: <https://github.com/vecorel/cli/compare/v0.2.7...v0.2.8>
[v0.2.7]: <https://github.com/vecorel/cli/compare/v0.2.6...v0.2.7>
[v0.2.6]: <https://github.com/vecorel/cli/compare/v0.2.5...v0.2.6>
[v0.2.5]: <https://github.com/vecorel/cli/compare/v0.2.4...v0.2.5>
[v0.2.4]: <https://github.com/vecorel/cli/compare/v0.2.3...v0.2.4>
[v0.2.3]: <https://github.com/vecorel/cli/compare/v0.2.2...v0.2.3>
[v0.2.2]: <https://github.com/vecorel/cli/compare/v0.2.1...v0.2.2>
[v0.2.1]: <https://github.com/vecorel/cli/compare/v0.2.0...v0.2.1>
[v0.2.0]: <https://github.com/vecorel/cli/compare/v0.1.0...v0.2.0>
[v0.1.0]: <https://github.com/vecorel/cli/compare/v0.1.0>
