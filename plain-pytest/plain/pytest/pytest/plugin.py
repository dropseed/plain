"""A pytest plugin which helps testing Plain applications

This plugin handles creating and destroying the test environment and
test database and provides some useful text fixtures.
"""


import pytest

from .fixtures import (
    _plain_db_helper,  # noqa
    plain_assert_max_num_queries,  # noqa
    plain_assert_num_queries,  # noqa
    plain_db_reset_sequences,  # noqa
    plain_db_serialized_rollback,  # noqa
    plain_db_setup,  # noqa
    client,  # noqa
    db,  # noqa
    rf,  # noqa
    settings,  # noqa
    transactional_db,  # noqa
    validate_plain_db,
)

TYPE_CHECKING = False
if TYPE_CHECKING:
    from typing import ContextManager, NoReturn

    import plain.runtime


# ############### pytest hooks ################


@pytest.hookimpl()
def pytest_addoption(parser) -> None:
    group = parser.getgroup("plain")
    group.addoption(
        "--reuse-db",
        action="store_true",
        dest="reuse_db",
        default=False,
        help="Re-use the testing database if it already exists, "
        "and do not remove it when the test finishes.",
    )
    group.addoption(
        "--create-db",
        action="store_true",
        dest="create_db",
        default=False,
        help="Re-create the database, even if it exists. This "
        "option can be used to override --reuse-db.",
    )

    parser.addini(
        "plain_debug_mode",
        "How to set the Plain DEBUG setting (default `False`). "
        "Use `keep` to not override.",
        default="False",
    )


def _setup_plain() -> None:
    import plain.runtime

    plain.runtime.setup()

    _blocking_manager.block()


def _get_boolean_value(
    x: None | bool | str,
    name: str,
    default: bool | None = None,
) -> bool:
    if x is None:
        return bool(default)
    if isinstance(x, bool):
        return x
    possible_values = {"true": True, "false": False, "1": True, "0": False}
    try:
        return possible_values[x.lower()]
    except KeyError:
        possible = ", ".join(possible_values)
        raise ValueError(
            f"{x} is not a valid value for {name}. It must be one of {possible}."
        )


@pytest.hookimpl()
def pytest_load_initial_conftests(
    early_config,
    parser,
    args: list[str],
) -> None:
    # Register the marks
    early_config.addinivalue_line(
        "markers",
        "plain_db(transaction=False, reset_sequences=False, databases=None, "
        "serialized_rollback=False): "
        "Mark the test as using the Plain test database.  "
        "The *transaction* argument allows you to use real transactions "
        "in the test like Plain's TransactionTestCase.  "
        "The *reset_sequences* argument resets database sequences before "
        "the test.  "
        "The *databases* argument sets which database aliases the test "
        "uses (by default, only 'default'). Use '__all__' for all databases.  "
        "The *serialized_rollback* argument enables rollback emulation for "
        "the test.",
    )
    early_config.addinivalue_line(
        "markers",
        "urls(modstr): Use a different URLconf for this test, similar to "
        "the `urls` attribute of Plain's `TestCase` objects.  *modstr* is "
        "a string specifying the module of a URL config, e.g. "
        '"my_app.test_urls".',
    )
    early_config.addinivalue_line(
        "markers",
        "ignore_template_errors(): ignore errors from invalid template "
        "variables (if --fail-on-template-vars is used).",
    )

    options = parser.parse_known_args(args)

    if options.version or options.help:
        return

    _setup_plain()


@pytest.hookimpl(trylast=True)
def pytest_configure() -> None:
    # Allow Plain settings to be configured in a user pytest_configure call,
    # but make sure we call plain.setup()
    _setup_plain()


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    def get_order_number(test: pytest.Item) -> int:
        marker_db = test.get_closest_marker("plain_db")
        if marker_db:
            (
                transaction,
                reset_sequences,
                databases,
                serialized_rollback,
            ) = validate_plain_db(marker_db)
            uses_db = True
            transactional = transaction or reset_sequences
        else:
            uses_db = False
            transactional = False
        fixtures = getattr(test, "fixturenames", [])
        transactional = transactional or "transactional_db" in fixtures
        uses_db = uses_db or "db" in fixtures

        if transactional:
            return 1
        elif uses_db:
            return 0
        else:
            return 2

    items.sort(key=get_order_number)


@pytest.fixture(autouse=True, scope="session")
def plain_test_environment(request) -> None:
    """
    Ensure that Plain is loaded and has its testing environment setup.

    XXX It is a little dodgy that this is an autouse fixture.  Perhaps
        an email fixture should be requested in order to be able to
        use the Plain email machinery just like you need to request a
        db fixture for access to the Plain database, etc.  But
        without duplicating a lot more of Plain's test support code
        we need to follow this model.
    """
    _setup_plain()
    from plain.test.utils import (
        setup_test_environment,
        teardown_test_environment,
    )

    debug_ini = request.config.getini("plain_debug_mode")
    if debug_ini == "keep":
        debug = None
    else:
        debug = _get_boolean_value(debug_ini, "plain_debug_mode", False)

    setup_test_environment(debug=debug)
    request.addfinalizer(teardown_test_environment)


@pytest.fixture(scope="session")
def plain_db_blocker() -> "_DatabaseBlocker | None":
    """Wrapper around Plain's database access.

    This object can be used to re-enable database access.  This fixture is used
    internally in pytest-plain to build the other fixtures and can be used for
    special database handling.

    The object is a context manager and provides the methods
    .unblock()/.block() and .restore() to temporarily enable database access.

    This is an advanced feature that is meant to be used to implement database
    fixtures.
    """
    return _blocking_manager


@pytest.fixture(autouse=True)
def _plain_db_marker(request) -> None:
    """Implement the plain_db marker, internal to pytest-plain."""
    marker = request.node.get_closest_marker("plain_db")
    if marker:
        request.getfixturevalue("_plain_db_helper")


@pytest.fixture(autouse=True)
def _dj_autoclear_mailbox() -> None:
    try:
        from plain import mail

        del mail.outbox[:]
    except ImportError:
        pass


@pytest.fixture()
def mailoutbox(
    plain_mail_patch_dns: None,
    _dj_autoclear_mailbox: None,
) -> "list[plain.mail.EmailMessage] | None":
    try:
        from plain import mail

        return mail.outbox
    except ImportError:
        pass


@pytest.fixture()
def plain_mail_patch_dns(
    monkeypatch,
    plain_mail_dnsname: str,
) -> None:
    try:
        from plain import mail

        monkeypatch.setattr(mail.message, "DNS_NAME", plain_mail_dnsname)
    except ImportError:
        pass


@pytest.fixture()
def plain_mail_dnsname() -> str:
    return "fake-tests.example.com"


# ############### Helper Functions ################


class _DatabaseBlockerContextManager:
    def __init__(self, db_blocker) -> None:
        self._db_blocker = db_blocker

    def __enter__(self) -> None:
        pass

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._db_blocker.restore()


class _DatabaseBlocker:
    """Manager for plain.models.backends.base.base.BaseDatabaseWrapper.

    This is the object returned by plain_db_blocker.
    """

    def __init__(self):
        self._history = []
        self._real_ensure_connection = None

    @property
    def _dj_db_wrapper(self) -> "plain.models.backends.base.base.BaseDatabaseWrapper":
        from plain.models.backends.base.base import BaseDatabaseWrapper

        # The first time the _dj_db_wrapper is accessed, we will save a
        # reference to the real implementation.
        if self._real_ensure_connection is None:
            self._real_ensure_connection = BaseDatabaseWrapper.ensure_connection

        return BaseDatabaseWrapper

    def _save_active_wrapper(self) -> None:
        self._history.append(self._dj_db_wrapper.ensure_connection)

    def _blocking_wrapper(*args, **kwargs) -> "NoReturn":
        __tracebackhide__ = True
        __tracebackhide__  # Silence pyflakes
        raise RuntimeError(
            "Database access not allowed, "
            'use the "plain_db" mark, or the '
            '"db" or "transactional_db" fixtures to enable it.'
        )

    def unblock(self) -> "ContextManager[None]":
        """Enable access to the Plain database."""
        self._save_active_wrapper()
        self._dj_db_wrapper.ensure_connection = self._real_ensure_connection
        return _DatabaseBlockerContextManager(self)

    def block(self) -> "ContextManager[None]":
        """Disable access to the Plain database."""
        self._save_active_wrapper()
        self._dj_db_wrapper.ensure_connection = self._blocking_wrapper
        return _DatabaseBlockerContextManager(self)

    def restore(self) -> None:
        self._dj_db_wrapper.ensure_connection = self._history.pop()


_blocking_manager = _DatabaseBlocker()


def validate_urls(marker) -> list[str]:
    """Validate the urls marker.

    It checks the signature and creates the `urls` attribute on the
    marker which will have the correct value.
    """

    def apifun(urls: list[str]) -> list[str]:
        return urls

    return apifun(*marker.args, **marker.kwargs)
