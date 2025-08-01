import sys
from logging import Logger

from loguru import logger


def format_logs(record):
    end = record["extra"].get("end", "\n")
    start = record["extra"].get("start", "")
    return start + "<level>{message}</level>" + end


class LoggerMixin:
    verbose: bool = True  # todo: set to False before release
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
    def print_pretty(self, data, depth=0, strlen=50):
        formatted = self._format_data(data, depth, strlen).strip()
        LoggerMixin.logger.opt(colors=True, raw=True).log("INFO", f"<n>{formatted}</n>\n")

    def _indent_text(self, text: str, indent: str) -> str:
        indent2 = "\n" + " " * len(indent)
        lines = text.splitlines()
        return indent + indent2.join(lines)

    def _format_data(self, value: dict, depth=0, strlen=50):
        if hasattr(value, "to_dict"):
            value = value.to_dict()

        output = ""
        prefix = "  " * depth
        if isinstance(value, dict):
            if depth <= 1:
                if depth > 0:
                    output += "\n"
                for key, value in value.items():
                    output += f"<blue>{key}</blue>: "
                    output += self._format_data(value, depth=depth + 1, strlen=strlen)
                return output
            else:
                return f"<yellow>object (omitted, {len(value)} key/value pairs)</yellow>\n"
        elif isinstance(value, list):
            if depth <= 1:
                if depth > 0:
                    output += "\n"
                for item in value:
                    output += f"{prefix}- "
                    output += self._format_data(item, depth=depth + 1, strlen=strlen)
                return output
            else:
                return f"<yellow>array (omitted, {len(value)} elements)</yellow>\n"

        if not isinstance(value, str):
            value = str(value)

        length = len(value)
        if strlen >= 0 and length > strlen:
            output += value[:strlen]
            if len(value) > strlen:
                output += f"<yellow>... ({length - strlen} chars omitted)</yellow>"
        else:
            output += value

        if len(prefix) > 0:
            output = self._indent_text(output, prefix).lstrip()

        return output + "\n"
