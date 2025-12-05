from __future__ import annotations

import os
from typing import Any

import click
from click.formatting import iter_rows, measure_table, term_len, wrap_text


class PlainHelpFormatter(click.HelpFormatter):
    def write_heading(self, heading: str) -> None:
        styled_heading = click.style(heading, dim=True)
        self.write(f"{'':>{self.current_indent}}{styled_heading}\n")

    def write_usage(  # type: ignore[override]
        self, prog: str, args: str = "", prefix: str = "Usage: "
    ) -> None:
        prefix_styled = click.style(prefix, dim=True)
        super().write_usage(prog, args, prefix=prefix_styled)

    def write_dl(  # type: ignore[override]
        self,
        rows: list[tuple[str, str]],
        col_max: int = 20,
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
                # Dim the description text
                first_line_styled = click.style(lines[0], dim=True)
                self.write(f"{first_line_styled}\n")

                for line in lines[1:]:
                    line_styled = click.style(line, dim=True)
                    self.write(
                        f"{'':>{first_col + self.current_indent}}{line_styled}\n"
                    )
            else:
                self.write("\n")


class PlainContext(click.Context):
    formatter_class = PlainHelpFormatter

    def __init__(self, *args: Any, **kwargs: Any):
        # Set a wider max_content_width for help text (default is 80)
        # This allows descriptions to fit more comfortably on one line
        if "max_content_width" not in kwargs:
            kwargs["max_content_width"] = 140

        super().__init__(*args, **kwargs)

        # Follow CLICOLOR standard (http://bixense.com/clicolors/)
        # Priority: NO_COLOR > CLICOLOR_FORCE/FORCE_COLOR > CI detection > CLICOLOR > isatty
        if os.getenv("NO_COLOR") or os.getenv("PYTEST_CURRENT_TEST"):
            self.color = False
        elif os.getenv("CLICOLOR_FORCE") or os.getenv("FORCE_COLOR"):
            self.color = True
        elif os.getenv("CI"):
            # Enable colors in CI/deployment environments even without TTY
            # This matches behavior of modern tools like uv (via Rust's anstyle)
            self.color = True
        elif os.getenv("CLICOLOR"):
            # CLICOLOR=1 means use colors only if TTY (Click's default behavior)
            pass  # Let Click handle it with isatty check
        # Otherwise use Click's default behavior (isatty check)
