from pathlib import Path
from typing import Union

from ..registry import Registry
from .base import BaseEncoding


def create_encoding(filepath: Union[Path, str]) -> BaseEncoding:
    """
    Create an encoding object based on the file extension.
    """
    filepath = Path(filepath)

    for encoding in Registry.encodings:
        if filepath.suffix in encoding.ext:
            return encoding(filepath)

    raise ValueError(f"Unsupported file type: {filepath.suffix}")
