"""A credential-shaped setting name is either `Secret[...]` or says `PUBLIC`.

`Secret[...]` is the only thing that masks a setting's value in the startup
"Settings from env" dump, `plain settings list`, and the admin settings
pages. A credential annotated as a plain `str` gets printed in full into
production logs.

The name pattern is a prompt to decide, not the decision — what settles it
is what the value *is* and who reads it. An SMTP username is a credential
because providers like Postmark use the API token itself as the username; a
pageview token is not, because the template tag renders it into every page's
HTML. But the decision has to end up in the name: a setting whose last word
is TOKEN / KEY / SECRET / PASSWORD / USER either carries `Secret[...]` or
carries `PUBLIC` in its name, so the name alone tells a reader which it is.

Only the last underscore-separated segment is read, because that is the word
that says what the value is: `EMAIL_HOST_USER` is a username, while
`AUTH_USER_SESSION_HASH_FIELD` is a field name and `PASSWORD_HASHERS` is a
list of classes. Names that carry a credential word anywhere but last
(`SECRET_KEY_FALLBACKS`) are settled by review, not by this rule.
"""

import ast
from pathlib import Path

from plain.runtime import settings

# The trailing noun that means "this value is a credential".
CREDENTIAL_WORDS = frozenset(
    {
        "TOKEN",
        "TOKENS",
        "KEY",
        "KEYS",
        "SECRET",
        "SECRETS",
        "PASSWORD",
        "PASSWORDS",
        "USER",
        "USERNAME",
        "DSN",
        "CREDENTIAL",
        "CREDENTIALS",
    }
)

# The escape hatch, spelled in the name itself rather than in a list here.
PUBLIC_WORD = "PUBLIC"


def needs_secret(name: str) -> bool:
    segments = name.split("_")
    if PUBLIC_WORD in segments:
        return False
    return segments[-1] in CREDENTIAL_WORDS


FIX = (
    "Annotate it Secret[T] if the value is a credential, or rename it to say "
    "PUBLIC (e.g. CONNECT_PAGEVIEWS_PUBLIC_TOKEN) if it is safe to print."
)


def test_registered_credential_settings_are_secret():
    """Every setting registered in this app — the same enumeration
    `plain settings list` prints — masks its value if it is a credential."""
    offenders = [
        name
        for name, defn in settings.get_settings()
        if needs_secret(name) and not defn.is_secret
    ]
    assert not offenders, (
        f"Credential-named settings not annotated Secret[...]: {offenders}. {FIX}"
    )


# --- Repo-wide scan -------------------------------------------------------
#
# The registry above only sees packages this test app installs, so it can't
# see EMAIL_HOST_USER or the CONNECT_* settings. Read every package's
# settings module straight off disk instead — as source, so no package has
# to be installed or importable.

REPO_ROOT = Path(__file__).parents[3]


def settings_modules() -> list[Path]:
    # e.g. plain-email/plain/email/default_settings.py. Three levels deep, so
    # the four-deep test fixture plain/tests/app/test/ stays out.
    paths = sorted(REPO_ROOT.glob("*/*/*/default_settings.py"))
    paths.append(REPO_ROOT / "plain" / "plain" / "runtime" / "global_settings.py")
    return [p for p in paths if p.is_file()]


def is_secret_annotation(node: ast.expr | None) -> bool:
    """True for `Secret[T]` — bare `Secret` or `module.Secret`, subscripted."""
    if not isinstance(node, ast.Subscript):
        return False
    target = node.value
    if isinstance(target, ast.Name):
        return target.id == "Secret"
    if isinstance(target, ast.Attribute):
        return target.attr == "Secret"
    return False


def test_repo_default_settings_are_secret():
    modules = settings_modules()
    # A scan that silently matches nothing would pass while proving nothing,
    # so pin a module that must always be in it.
    assert REPO_ROOT / "plain-email/plain/email/default_settings.py" in modules, (
        f"Settings scan found {len(modules)} modules under {REPO_ROOT} and is "
        f"not reaching the packages — fix the glob before trusting this test."
    )

    offenders = []
    for path in modules:
        tree = ast.parse(path.read_text(), filename=str(path))
        # walk() rather than tree.body — plain.auth declares settings inside
        # an `if find_spec(...)` block.
        for node in ast.walk(tree):
            if not isinstance(node, ast.AnnAssign):
                continue
            if not isinstance(node.target, ast.Name):
                continue
            name = node.target.id
            if not name.isupper() or not needs_secret(name):
                continue
            if not is_secret_annotation(node.annotation):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} {name}")

    assert not offenders, (
        "Credential-named settings not annotated Secret[...]:\n  "
        + "\n  ".join(offenders)
        + f"\n{FIX}"
    )
