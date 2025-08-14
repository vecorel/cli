import re
import sys
from logging import Logger

from loguru import logger


def format_logs(record):
    end = record["extra"].get("end", "\n")
    start = record["extra"].get("start", "")
    return start + "<level>{message}</level>" + end


class LoggerMixin:
    verbose: bool = False
    logger: Logger = None

    def __init__(self):
        if LoggerMixin.logger is None:
            logger.remove()
            LoggerMixin.logger = logger
            LoggerMixin.logger.add(
                sys.stdout,
                colorize=True,
                format=format_logs,
                level="DEBUG" if self.verbose else "INFO",
            )

    def debug(self, message: str, **kwargs):
        self.log(message, "debug", **kwargs)

    def info(self, message: str, **kwargs):
        self.log(message, "info", **kwargs)

    def warning(self, message: str, **kwargs):
        self.log(message, "warning", **kwargs)

    def error(self, message: str, **kwargs):
        self.log(message, "error", **kwargs)

    def success(self, message: str, **kwargs):
        self.log(message, "success", **kwargs)

    def log(
        self,
        message,
        level: str = "info",
        start="",
        end="\n",
        indent="",
        color=None,
        style="normal",
    ):
        if not isinstance(message, str):
            message = str(message)

        # Escape special characters
        message = re.sub(r"(<\w+>)", r"\\\1", message, 0, re.IGNORECASE)

        # Handle indentation (including multiple lines)
        message = self._indent_text(message, indent)

        # Coloring and Styling
        if color is not None:
            message = f"<{color}>{message}</{color}>"
        if style is not None:
            message = f"<{style}>{message}</{style}>"

        # Default template for the message
        message = start + f"<level>{message}</level>" + end

        # Log it
        LoggerMixin.logger.opt(colors=True, raw=True).bind(start=start, end=end).log(
            level.upper(), message
        )

    def exception(self, e: Exception):
        LoggerMixin.logger.exception(e)

    # strlen = -1 disables truncation
    def print_pretty(self, data, depth=0, max_depth=1, strlen=50):
        formatted = self._format_data(data, depth=depth, max_depth=max_depth, strlen=strlen).strip(
            "\r\n"
        )
        LoggerMixin.logger.opt(colors=True, raw=True).log("INFO", f"<n>{formatted}</n>\n")

    def _indent_text(self, text: str, indent: str) -> str:
        indent2 = "\n" + " " * len(indent)
        lines = text.splitlines()
        return indent + indent2.join(lines)

    def _format_data(self, value: dict, depth=0, max_depth=1, strlen=50):
        if hasattr(value, "to_dict"):
            value = value.to_dict()

        output = ""
        prefix = "  " * depth
        if isinstance(value, dict):
            if depth <= max_depth:
                if depth > 0:
                    output += "\n"
                for key, value in value.items():
                    output += f"{prefix}<cyan>{key}</>: "
                    output += self._format_data(
                        value, depth=depth + 1, max_depth=max_depth, strlen=strlen
                    )
                return output
            else:
                return f"<yellow>object (omitted, {len(value)} key/value pairs)</>\n"
        elif isinstance(value, list):
            if depth <= max_depth:
                if depth > 0:
                    output += "\n"
                for item in value:
                    output += f"{prefix}- "
                    output += self._format_data(
                        item, depth=depth + 1, max_depth=max_depth, strlen=strlen
                    )
                return output
            else:
                return f"<yellow>array (omitted, {len(value)} elements)</>\n"

        if not isinstance(value, str):
            value = str(value)

        length = len(value)
        if strlen >= 0 and length > strlen:
            output += value[:strlen]
            if len(value) > strlen:
                output += f"<yellow>... ({length - strlen} chars omitted)</>"
        else:
            output += value

        if len(prefix) > 0:
            output = self._indent_text(output, prefix).lstrip()

        return output + "\n"
