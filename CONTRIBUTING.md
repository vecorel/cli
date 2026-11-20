# Contributing to Vecorel CLI

Thanks for contributing! The [Development](README.md#development) section of the README explains the
setup. The guidelines below collect what reviews ask for most often.

## Scope

- Vecorel CLI is generic: nothing specific to fiboa, an extension or a dataset belongs here.
- Behaviour that several converters need belongs here, not in each downstream converter. Offer it
  as a declarative attribute on `BaseConverter` (like `crs`, `side_files`, `id_columns`) that a
  converter sets, not as a method it has to override.
- fiboa CLI and other tools build on the converter attributes and hooks. Keep them backwards
  compatible where possible.
- Schemas use the Vecorel SDL, which is not JSON Schema. Only support the keywords that the SDL
  defines.

## Code

- Reuse what exists instead of adding a second copy that can disagree with the first, e.g. the
  type mappings in `vecorel_cli/parquet/types.py`, `_sql_name` for SQL identifiers, or the
  existing CRS checks.
- The GeoPandas and DuckDB paths (converters and `vec merge`) must give the same results. Change
  and test both.
- Fail with a clear error instead of guessing, silently falling back or dropping data. Don't add
  implicit defaults that hide a problem.
- Don't add code for niche cases that no dataset has. Add it when a dataset needs it.
- For changes on the conversion or write path, measure the cost on large datasets (millions of
  rows).
- Change dependencies in `pyproject.toml` and `pixi.lock` together. CI tests the oldest and
  newest supported Python through the pixi environments `dev-py311` and `dev-py314`.

## Tests

- Keep tests proportionate.
- Tests and fixtures must actually exercise the code paths they are meant to cover.

## Changelog and pull requests

- Every non-trivial change needs a `CHANGELOG.md` entry (CI checks it).
- Changelog entries are short and user-facing, without internals, in Added / Changed / Fixed / etc.
- Keep PRs small and focused (one topic) and target `main`. Say if a PR depends on another one.
- Keep code comments and PR descriptions short.
- Run `pixi run -e dev check` (lint, format, tests) before pushing.
