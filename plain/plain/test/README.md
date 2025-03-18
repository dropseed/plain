# Test

**Testing utilities for Plain.**

This module provides a the [`Client`](client.py#Client) and [`RequestFactory`](client.py#RequestFactory) classes to facilitate testing requests and responses.

```python
from plain.test import Client


def test_client_example():
    client = Client()

    # Getting responses
    response = client.get("/")
    assert response.status_code == 200

    # Modifying sessions
    client.session["example"] = "value"
    assert client.session["example"] == "value"

    # Logging in
    user = User.objects.first()
    client.force_login(user)
    response = client.get("/protected/")
    assert response.status_code == 200

    # Logging out
    client.logout()
    response = client.get("/protected/")
    assert response.status_code == 302

def test_request_factory_example():
    request = RequestFactory().get("/")
    assert request.method == "GET"
```

More complete testing utilities are provided by the [`plain.pytest`](/plain-pytest/README.md) package. The [`plain.models`](/plain-models/README.md) package also provides pytest fixtures for database testing.
