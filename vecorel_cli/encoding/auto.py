from pathlib import Path
from typing import Union

from yarl import URL

from ..registry import Registry
from .base import BaseEncoding


def create_encoding(filepath: Union[Path, URL, str]) -> BaseEncoding:
    """
    Create an encoding object based on the file extension.
    """
    if isinstance(filepath, str):
        filepath = Path(filepath)

    for encoding in Registry.get_encodings():
        if isinstance(filepath, URL):
            ext = Path(filepath.path).suffix
        else:
            ext = filepath.suffix

        if ext in encoding.ext:
            return encoding(filepath)

    raise ValueError(f"Unsupported file type: {ext}")
