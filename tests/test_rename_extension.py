import tempfile
from pathlib import Path

import git
from loguru import logger
from pytest import fixture

from vecorel_cli.encoding.auto import create_encoding
from vecorel_cli.rename_extension import RenameExtension

TEMPLATE_REPO = "https://github.com/vecorel/extension-template.git"


@fixture
def cloned_repo():
    """Fixture that clones a repository for testing."""
    with tempfile.TemporaryDirectory() as folder:
        logger.remove()  # Remove default logger to avoid cluttering output
        repo = git.Repo.clone_from(TEMPLATE_REPO, folder)
        yield Path(folder), repo


def test_rename_extension(cloned_repo):
    folder, repo = cloned_repo

    RenameExtension(
        title="Test",
        repo="test-extension",
        org="fiboa",
        prefix="test",
    ).rename(folder)

    # Check if the README.md was created with the correct title
    readme_path = folder / "README.md"
    assert readme_path.exists(), "README.md not present"
    readme = readme_path.read_text()
    assert "# Test Extension Specification" in readme
    assert "- **Title:** Test" in readme
    assert "- **Identifier:** <https://fiboa.github.io/test-extension/v0.1.0/schema.yaml>" in readme
    assert "- **Property Name Prefix:** test" in readme
    assert "| test:field2 | int32  | Describe the field... |" in readme
    assert "template" not in readme
    assert "Template" not in readme

    schema_path = folder / "schema" / "schema.yaml"
    assert schema_path.exists(), "schema.yaml not present"
    assert "template" not in readme
    assert "test:field1" in readme
    assert "test:field2" in readme

    schema_map = {
        "https://fiboa.github.io/test-extension/v0.1.0/schema.yaml": schema_path.absolute()
    }
    examples = [
        folder / "examples" / "geojson" / "example.json",
        folder / "examples" / "geoparquet" / "example.parquet",
    ]
    for p in examples:
        assert p.exists(), f"{p.name} not present"
        enc = create_encoding(p)
        data = enc.read(schema_map=schema_map)
        assert "test:field1" in data, f"test:field1 not found in {p.name}"
        assert "test:field2" in data, f"test:field2 not found in {p.name}"
