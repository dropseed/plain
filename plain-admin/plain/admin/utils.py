import hashlib
import re
from typing import Any


def camelcase_to_title(name: str) -> str:
    """Convert CamelCase to a readable title.

    Examples:
        User -> User
        ThisThing -> This thing
        URLParser -> URL parser
    """
    # Insert space before:
    # - capitals that follow lowercase letters or digits
    # - a capital followed by lowercase (for acronyms like URLParser)
    # - digits that follow letters
    result = re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[a-zA-Z])(?=[0-9])",
        " ",
        name,
    )
    # Capitalize first letter, lowercase the rest of each word except acronyms
    words = result.split()
    if not words:
        return name
    # First word: capitalize first letter
    # Remaining words: lowercase unless all caps (acronym)
    processed = [words[0]]
    for word in words[1:]:
        if word.isupper() and len(word) > 1:
            processed.append(word)  # Keep acronyms uppercase
        else:
            processed.append(word.lower())
    return " ".join(processed)


def get_gravatar_url(user: Any) -> str | None:
    """Generate gravatar URL for the given user if they have an email address."""
    if not user or not hasattr(user, "email") or not user.email:
        return None

    # Create hash of email
    email_hash = hashlib.md5(user.email.lower().strip().encode("utf-8")).hexdigest()

    # Return gravatar URL with default identicon fallback
    return f"https://www.gravatar.com/avatar/{email_hash}?s=64&d=identicon"
