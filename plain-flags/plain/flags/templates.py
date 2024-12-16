from plain.templates import register_template_global

from .bridge import get_flags_module

register_template_global(get_flags_module(), name="flags")
