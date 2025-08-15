from semantic_version import SimpleSpec, Version

vecorel_version = "0.1.0"
supported_vecorel_versions = ">=0.1.0,<0.2.0"
supported_sdl_versions = ">=0.2.0,<0.3.0"
sdl_uri = "https://vecorel.org/sdl/v0.2.0/schema.json"


def is_supported(version, raise_exception=False) -> bool:
    result = check_versions(version, supported_vecorel_versions)
    if not result and raise_exception:
        raise ValueError(
            f"Vecorel version {version} is not supported, supported are {supported_vecorel_versions}"
        )
    return result


def is_sdl_supported(version, raise_exception=False) -> bool:
    result = check_versions(version, supported_sdl_versions)
    if not result and raise_exception:
        raise ValueError(
            f"Vecorel Schema Definition Language (SDL) version {version} is not supported, supported are {supported_sdl_versions}"
        )
    return result


def check_versions(version, range) -> bool:
    if not isinstance(version, str):
        return False
    supported = SimpleSpec(range)
    return supported.match(Version(version))
