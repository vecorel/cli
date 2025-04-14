import inspect
import sys
from pathlib import Path
from typing import Union

import click

from .registry import Registry

LOG_STATUS_COLOR = {
    "info": "white",
    "warning": "yellow",
    "error": "red",
    "success": "green",
    "debug": "blue",
}


def runnable(func):
    func._is_runnable = True
    return func


class BaseCommand:
    verbose: bool = True  # todo: set to False before release

    cmd_name: str = ""
    cmd_title: str = ""
    cmd_help: str = ""
    cmd_final_report: bool = False

    @staticmethod
    def get_cli_command(cmd) -> click.Command:
        return click.Command(cmd.cmd_name, help=cmd.cmd_help, callback=cmd.get_cli_callback(cmd))

    @staticmethod
    def get_cli_args() -> dict[str, Union[click.Option, click.Argument]]:
        return {}

    @staticmethod
    def get_cli_callback(cmd):
        return cmd().run

    def run(self, *args, **kwargs):
        # Print header
        self.log(f"{Registry.cli_title} {Registry.cli_version} - {self.cmd_title}\n")

        # Detect method to run
        fn = None
        for _, method in inspect.getmembers(self, predicate=inspect.ismethod):
            if getattr(method, "_is_runnable", False):
                fn = method
                break
        if not fn:
            raise RuntimeError("No method marked with @runnable found.")

        # Run main method
        if self.verbose:
            result = fn(*args, **kwargs)
        else:
            try:
                result = fn(*args, **kwargs)
            except Exception as e:
                self.log(e, "error")
                sys.exit(1)

        # Report command as finished
        if self.cmd_final_report:
            if isinstance(result, Path):
                self.log(f"Finished - Result: {result.absolute()}", "success")
            elif not result:
                self.log("Finished", "success")
            else:
                self.log(result, "success")

        # Return result
        return result

    def log(self, text: Union[str, Exception], status="info", nl=True, **kwargs):
        """Log a message with a severity level (which leads to different colors)"""
        click.echo(click.style(text, fg=LOG_STATUS_COLOR[status], **kwargs), nl=nl)

    def set_verbose(self, verbose: bool = True):
        self.verbose = verbose
