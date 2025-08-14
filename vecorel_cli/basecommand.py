import inspect
import json
import sys
from pathlib import Path
from typing import Union

import click

from .cli.logger import LoggerMixin
from .registry import Registry


def runnable(func):
    func._is_runnable = True
    return func


class BaseCommand(LoggerMixin):
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
        self.info(
            f"{Registry.cli_title} {Registry.get_version()} - {self.cmd_title}",
            end="\n\n",
            style="bold",
            color="cyan",
        )

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
                self.exception(e)
                sys.exit(1)

        # Report command as finished
        if self.cmd_final_report:
            if isinstance(result, Path):
                self.success(f"Finished - Result: {result.absolute()}")
            elif not result:
                self.success("Finished")
            else:
                self.success(result)

        # Return result
        return result

    def _json_dump_cli(self, obj, target=None, indent=None):
        target = Path(target) if target else None
        if target:
            with open(target, "w", encoding="utf-8") as f:
                json.dump(obj, f, indent=indent)
            return target
        else:
            return json.dumps(obj, indent=indent)
