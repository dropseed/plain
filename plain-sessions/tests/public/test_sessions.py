import pytest

from plain.sessions import SessionNotAvailable, get_request_session
from plain.sessions.core import SessionStore
from plain.sessions.models import Session
from plain.test import Client, RequestFactory


def test_session_created(db):
    assert Session.query.count() == 0

    response = Client().get("/")

    assert response.status_code == 200

    assert Session.query.count() == 1


def test_mapping_attributes(db):
    store = SessionStore()
    assert store.accessed is False
    assert store.modified is False
    assert len(store) == 0

    # accessing without modifying
    assert store.get("foo") is None
    assert store.accessed is True
    assert store.modified is False

    assert "foo" not in store
    assert store.pop("foo", "a") == "a"

    # setting a value modifies the session
    store["foo"] = "bar"
    assert store.modified is True
    assert store["foo"] == "bar"

    # update via MutableMapping.update
    store.update({"a": 1, "b": 2})
    assert set(store.keys()) == {"foo", "a", "b"}
    assert len(store) == 3
    assert store.modified is True

    # deleting a key modifies the session
    del store["foo"]
    assert "foo" not in store
    assert len(store) == 2

    # clearing empties the session
    store.clear()
    assert store.is_empty()
    assert store.modified is True


def test_session_not_available():
    """Test that SessionNotAvailable is raised when session hasn't been set up."""
    rf = RequestFactory()
    request = rf.get("/")

    # Session hasn't been set up by middleware yet
    with pytest.raises(SessionNotAvailable) as exc_info:
        get_request_session(request)

    assert "Session is not available" in str(exc_info.value)
    assert "SessionMiddleware" in str(exc_info.value)
