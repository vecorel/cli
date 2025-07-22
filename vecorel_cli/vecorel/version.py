from semantic_version import SimpleSpec

vecorel_version = "0.1.0"
supported_vecorel_versions = ">=0.1.0,<0.2.0"


def is_supported(version):
    supported = SimpleSpec(supported_vecorel_versions)
    return supported.match(version)
