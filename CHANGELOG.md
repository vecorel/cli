# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [v0.2.4] - 2025-08-27

- Encode numpy datatypes correctly when exporting to JSON
- Code refactoring

## [v0.2.3] - 2025-08-26

- Better support for merging schemas

## [v0.2.2] - 2025-08-25

- Make the whole library easier to rebrand and reuse
- Separate CLI creation from `__init__.py` files to avoid import race coditions
- Add return value to `ConvertData.check_datasets`
- Fix geopandas `datetime64` data type conversion issue

## [v0.2.1] - 2025-08-25

- Updated to use the Geometry Metrics Extension
- Fixed various hardcoded vecorel instances in rename-extension
- Fixed registry to be overridable by other CLI tools

## [v0.2.0] - 2025-08-15

- Migrate from vecorel.github.io to vecorel.org
- Add internal `py-package` parameter to the `convert` command
- Bugfixes

## [v0.1.0] - 2025-08-15

- First release based on vecorel CLI 0.1.0

[Unreleased]: <https://github.com/vecorel/cli/compare/v0.2.3...main>
[v0.2.3]: <https://github.com/vecorel/cli/compare/v0.2.2...v0.2.3>
[v0.2.2]: <https://github.com/vecorel/cli/compare/v0.2.1...v0.2.2>
[v0.2.1]: <https://github.com/vecorel/cli/compare/v0.2.0...v0.2.1>
[v0.2.0]: <https://github.com/vecorel/cli/compare/v0.1.0...v0.2.0>
[v0.1.0]: <https://github.com/vecorel/cli/compare/v0.1.0>
