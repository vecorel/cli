# Contributing to Vecorel CLI

Thanks for contributing! The [Development](README.md#development) section of the README explains the
setup. The guidelines below collect what reviews ask for most often.

## Responsibility and AI

- You are responsible for everything you contribute, no matter how it was made. Check all of it
  before you ask for a review: reviewing a contribution should take less work than making it.
- Comments, reviews and replies on GitHub that are addressed to people should be written by a human
  and concisely for a human.
- Saying in the PR that you used AI is appreciated. Commits don't need AI attribution, as the
  responsibility is entirely yours.

## Scope

- Vecorel CLI is generic: nothing specific to fiboa, an extension or a dataset belongs here.
- Behaviour that several converters need belongs here, ideally as a declarative attribute on the
  [base converter](vecorel_cli/conversion/base.py) rather than a method to override.
- fiboa CLI and other tools build on these attributes, so keep them backwards compatible where
  possible.
- Schemas use the [Vecorel SDL](https://github.com/vecorel/sdl), which is not JSON Schema.

## Converters

- A conversion with the [base converter](vecorel_cli/conversion/base.py) runs these steps in order:
  1. Download the `sources` and read them with `open_options`
  2. `file_migration` (per file), then reprojection to `crs`
  3. `migrate`
  4. `column_filters`
  5. `column_additions`
  6. `column_migrations`
  7. `post_migrate`
  8. Create the `id` (e.g. from `id_columns`) and drop rows that miss required values
  9. Rename the columns as listed in `columns`, fix the geometries, number repeated ids and drop all
     other columns

  Until step 9, the columns have the source's names.
- Keep this order when changing the base converter, as converters rely on it.

## Code

- Reuse existing helpers instead of adding a second copy that can disagree with the first.
- The GeoPandas and DuckDB paths must give the same results, so change and test both.
- Fail with a clear error instead of guessing, silently falling back or dropping data.
- Don't add code for niche cases until a dataset needs it.
- Measure the cost of changes to the conversion or write path on large datasets.
- Update `pixi.lock` together with the dependencies in `pyproject.toml`.

## Tests

- Keep tests proportionate, and make sure they cover what they claim to.

## Changelog and pull requests

- Every non-trivial change needs a `CHANGELOG.md` entry (CI checks it).
- Changelog entries are short and user-facing.
- Keep PRs small and focused on one topic, and say if a PR depends on another one.
- Keep code comments and PR descriptions short.
- Run `pixi run -e dev check` before pushing.
