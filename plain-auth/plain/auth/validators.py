import re

from plain import validators
from plain.utils.deconstruct import deconstructible


@deconstructible
class ASCIIUsernameValidator(validators.RegexValidator):
    regex = r"^[\w.@+-]+\Z"
    message = "Enter a valid username. This value may contain only unaccented lowercase a-z and uppercase A-Z letters, numbers, and @/./+/-/_ characters."
    flags = re.ASCII


@deconstructible
class UnicodeUsernameValidator(validators.RegexValidator):
    regex = r"^[\w.@+-]+\Z"
    message = "Enter a valid username. This value may contain only letters, numbers, and @/./+/-/_ characters."
    flags = 0
