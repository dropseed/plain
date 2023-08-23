"""A pytest plugin which helps testing Bolt applications

This plugin handles creating and destroying the test environment and
test database and provides some useful text fixtures.
"""

import contextlib
import os
import pathlib
import sys
from typing import Generator, List, Optional, Tuple, Union

import pytest

from .fixtures import (
    _bolt_db_helper,  # noqa
    bolt_assert_max_num_queries,  # noqa
    bolt_assert_num_queries,  # noqa
    bolt_db_reset_sequences,  # noqa
    bolt_db_serialized_rollback,  # noqa
    bolt_db_setup,  # noqa
    client,  # noqa
    db,  # noqa
    rf,  # noqa
    settings,  # noqa
    transactional_db,  # noqa
    validate_bolt_db,
)

TYPE_CHECKING = False
if TYPE_CHECKING:
    from typing import ContextManager, NoReturn

    import bolt.runtime


# ############### pytest hooks ################


@pytest.hookimpl()
def pytest_addoption(parser) -> None:
    group = parser.getgroup("bolt")
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
        "bolt_debug_mode",
        "How to set the Bolt DEBUG setting (default `False`). "
        "Use `keep` to not override.",
        default="False",
    )


def _setup_bolt() -> None:
    import bolt.runtime

    bolt.runtime.setup()

    _blocking_manager.block()


def _get_boolean_value(
    x: Union[None, bool, str],
    name: str,
    default: Optional[bool] = None,
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
    args: List[str],
) -> None:
    # Register the marks
    early_config.addinivalue_line(
        "markers",
        "bolt_db(transaction=False, reset_sequences=False, databases=None, "
        "serialized_rollback=False): "
        "Mark the test as using the Bolt test database.  "
        "The *transaction* argument allows you to use real transactions "
        "in the test like Bolt's TransactionTestCase.  "
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
        "the `urls` attribute of Bolt's `TestCase` objects.  *modstr* is "
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

    _setup_bolt()


@pytest.hookimpl(trylast=True)
def pytest_configure() -> None:
    # Allow Bolt settings to be configured in a user pytest_configure call,
    # but make sure we call bolt.setup()
    _setup_bolt()


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: List[pytest.Item]) -> None:
    def get_order_number(test: pytest.Item) -> int:
        marker_db = test.get_closest_marker("bolt_db")
        if marker_db:
            (
                transaction,
                reset_sequences,
                databases,
                serialized_rollback,
            ) = validate_bolt_db(marker_db)
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
def bolt_test_environment(request) -> None:
    """
    Ensure that Bolt is loaded and has its testing environment setup.

    XXX It is a little dodgy that this is an autouse fixture.  Perhaps
        an email fixture should be requested in order to be able to
        use the Bolt email machinery just like you need to request a
        db fixture for access to the Bolt database, etc.  But
        without duplicating a lot more of Bolt's test support code
        we need to follow this model.
    """
    _setup_bolt()
    from bolt.test.utils import (
        setup_test_environment,
        teardown_test_environment,
    )

    debug_ini = request.config.getini("bolt_debug_mode")
    if debug_ini == "keep":
        debug = None
    else:
        debug = _get_boolean_value(debug_ini, "bolt_debug_mode", False)

    setup_test_environment(debug=debug)
    request.addfinalizer(teardown_test_environment)


@pytest.fixture(scope="session")
def bolt_db_blocker() -> "Optional[_DatabaseBlocker]":
    """Wrapper around Bolt's database access.

    This object can be used to re-enable database access.  This fixture is used
    internally in pytest-bolt to build the other fixtures and can be used for
    special database handling.

    The object is a context manager and provides the methods
    .unblock()/.block() and .restore() to temporarily enable database access.

    This is an advanced feature that is meant to be used to implement database
    fixtures.
    """
    return _blocking_manager


@pytest.fixture(autouse=True)
def _bolt_db_marker(request) -> None:
    """Implement the bolt_db marker, internal to pytest-bolt."""
    marker = request.node.get_closest_marker("bolt_db")
    if marker:
        request.getfixturevalue("_bolt_db_helper")


@pytest.fixture(scope="function", autouse=True)
def _dj_autoclear_mailbox() -> None:
    try:
        from bolt import mail

        del mail.outbox[:]
    except ImportError:
        pass


@pytest.fixture(scope="function")
def mailoutbox(
    bolt_mail_patch_dns: None,
    _dj_autoclear_mailbox: None,
) -> "Optional[List[bolt.mail.EmailMessage]]":
    try:
        from bolt import mail

        return mail.outbox
    except ImportError:
        pass


@pytest.fixture(scope="function")
def bolt_mail_patch_dns(
    monkeypatch,
    bolt_mail_dnsname: str,
) -> None:
    try:
        from bolt import mail

        monkeypatch.setattr(mail.message, "DNS_NAME", bolt_mail_dnsname)
    except ImportError:
        pass


@pytest.fixture(scope="function")
def bolt_mail_dnsname() -> str:
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
    """Manager for bolt.db.backends.base.base.BaseDatabaseWrapper.

    This is the object returned by bolt_db_blocker.
    """

    def __init__(self):
        self._history = []
        self._real_ensure_connection = None

    @property
    def _dj_db_wrapper(self) -> "bolt.db.backends.base.base.BaseDatabaseWrapper":
        from bolt.db.backends.base.base import BaseDatabaseWrapper

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
            'use the "bolt_db" mark, or the '
            '"db" or "transactional_db" fixtures to enable it.'
        )

    def unblock(self) -> "ContextManager[None]":
        """Enable access to the Bolt database."""
        self._save_active_wrapper()
        self._dj_db_wrapper.ensure_connection = self._real_ensure_connection
        return _DatabaseBlockerContextManager(self)

    def block(self) -> "ContextManager[None]":
        """Disable access to the Bolt database."""
        self._save_active_wrapper()
        self._dj_db_wrapper.ensure_connection = self._blocking_wrapper
        return _DatabaseBlockerContextManager(self)

    def restore(self) -> None:
        self._dj_db_wrapper.ensure_connection = self._history.pop()


_blocking_manager = _DatabaseBlocker()


def validate_urls(marker) -> List[str]:
    """Validate the urls marker.

    It checks the signature and creates the `urls` attribute on the
    marker which will have the correct value.
    """

    def apifun(urls: List[str]) -> List[str]:
        return urls

    return apifun(*marker.args, **marker.kwargs)
