import sys
from typing import Union

import click

from .version import __version__

LOG_STATUS_COLOR = {"info": "white", "warning": "yellow", "error": "red", "success": "green"}


class BaseCommand:
    verbose: bool = True

    cli_title: str = "Vecorel CLI"
    cli_version: str = __version__

    cmd_title: str = ""
    cmd_fn: str = ""

    def run(self, *args, **kwargs):
        self.log(f"{self.cli_title} {self.cli_version} - {self.cmd_title}\n")
        if self.verbose:
            return getattr(self, self.cmd_fn)(*args, **kwargs)
        else:
            try:
                return getattr(self, self.cmd_fn)(*args, **kwargs)
            except Exception as e:
                self.log(e, "error")
                sys.exit(1)

    def log(self, text: Union[str, Exception], status="info", nl=True, **kwargs):
        """Log a message with a severity level (which leads to different colors)"""
        click.echo(click.style(text, fg=LOG_STATUS_COLOR[status], **kwargs), nl=nl)

    def set_verbose(self, verbose: bool = True):
        self.verbose = verbose

    @staticmethod
    def configure_cli(self, title: str, version: str):
        self.cli_title = title
        self.cli_version = version
