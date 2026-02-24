from __future__ import annotations

from typing import Any

import click


class SettingOption(click.Option):
    """A Click option that reads its value from Plain settings instead of os.environ.

    Usage:
        @click.option("--max-processes", cls=SettingOption, setting="JOBS_WORKER_MAX_PROCESSES")

    CLI args always take priority. The setting's value (including package
    defaults) is the single source of truth — no need for Click `default=`.
    """

    def __init__(self, *args: Any, setting: str | None = None, **kwargs: Any) -> None:
        if setting and kwargs.get("envvar"):
            raise ValueError(
                "Cannot use both 'setting' and 'envvar' on the same option. "
                "Use 'setting' to read from Plain settings."
            )
        if setting and "default" in kwargs:
            raise ValueError(
                "Cannot use both 'setting' and 'default' on the same option. "
                "The setting's default value is the single source of truth."
            )
        self.setting_name = setting
        if setting:
            kwargs.setdefault("show_default", True)
        super().__init__(*args, **kwargs)

    def get_default(self, ctx: click.Context, call: bool = True) -> Any:
        if self.setting_name:
            try:
                from plain.runtime import settings

                settings._setup()
                defn = settings._settings.get(self.setting_name)
                if defn is not None:
                    return defn.value
            except Exception:
                if ctx.resilient_parsing:
                    return None
                raise
        return super().get_default(ctx, call=call)

    def get_help_record(self, ctx: click.Context) -> tuple[str, str] | None:
        result = super().get_help_record(ctx)
        if result and self.setting_name:
            name, help_text = result
            setting_str = f"setting: {self.setting_name}"
            if help_text and help_text.rstrip().endswith("]"):
                bracket_start = help_text.rindex("[")
                inside = help_text[bracket_start + 1 : -1]
                help_text = f"{help_text[:bracket_start]}[{setting_str}; {inside}]"
            elif help_text:
                help_text = f"{help_text}  [{setting_str}]"
            else:
                help_text = f"[{setting_str}]"
            return name, help_text
        return result
