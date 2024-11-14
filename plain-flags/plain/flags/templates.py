from plain.templates import register_template_global

from .bridge import get_flags_module

register_template_global("flags", get_flags_module())
