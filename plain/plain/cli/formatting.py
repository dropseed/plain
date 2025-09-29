from __future__ import annotations

import os
from typing import Any

import click
from click.formatting import iter_rows, measure_table, term_len, wrap_text


class PlainHelpFormatter(click.HelpFormatter):
    def write_heading(self, heading: str) -> None:
        styled_heading = click.style(heading, underline=True)
        self.write(f"{'':>{self.current_indent}}{styled_heading}\n")

    def write_usage(self, prog: str, args: str = "", prefix: str = "Usage: ") -> None:
        prefix_styled = click.style(prefix, italic=True)
        super().write_usage(prog, args, prefix=prefix_styled)

    def write_dl(
        self,
        rows: list[tuple[str, str]],
        col_max: int = 30,
        col_spacing: int = 2,
    ) -> None:
        """Writes a definition list into the buffer.  This is how options
        and commands are usually formatted.

        :param rows: a list of two item tuples for the terms and values.
        :param col_max: the maximum width of the first column.
        :param col_spacing: the number of spaces between the first and
                            second column.
        """
        rows = list(rows)
        widths = measure_table(rows)
        if len(widths) != 2:
            raise TypeError("Expected two columns for definition list")

        first_col = min(widths[0], col_max) + col_spacing

        for first, second in iter_rows(rows, len(widths)):
            first_styled = click.style(first, bold=True)
            self.write(f"{'':>{self.current_indent}}{first_styled}")
            if not second:
                self.write("\n")
                continue
            if term_len(first) <= first_col - col_spacing:
                self.write(" " * (first_col - term_len(first)))
            else:
                self.write("\n")
                self.write(" " * (first_col + self.current_indent))

            text_width = max(self.width - first_col - 2, 10)
            wrapped_text = wrap_text(second, text_width, preserve_paragraphs=True)
            lines = wrapped_text.splitlines()

            if lines:
                self.write(f"{lines[0]}\n")

                for line in lines[1:]:
                    self.write(f"{'':>{first_col + self.current_indent}}{line}\n")
            else:
                self.write("\n")


class PlainContext(click.Context):
    formatter_class = PlainHelpFormatter

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)

        # Force colors in CI environments
        if any(
            os.getenv(var)
            for var in ["CI", "FORCE_COLOR", "GITHUB_ACTIONS", "GITLAB_CI"]
        ) and not any(os.getenv(var) for var in ["NO_COLOR", "PYTEST_CURRENT_TEST"]):
            self.color = True
