from plain.html.globals import register

from .bridge import get_flags_module

register("flags", get_flags_module())
