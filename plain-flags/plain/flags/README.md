# plain.flags

Local feature flags via database models.

Custom flags are written as subclasses of [`Flag`](./flags.py).
You define the flag's "key" and initial value,
and the results will be stored in the database for future reference.

```python
# app/flags.py
from plain.flags import Flag


class FooEnabled(Flag):
    def __init__(self, user):
        self.user = user

    def get_key(self):
        return self.user

    def get_value(self):
        # Initially all users will have this feature disabled
        # and we'll enable them manually in the admin
        return False
```

Use flags in HTML templates:

```html
{% if flags.FooEnabled(request.user) %}
    <p>Foo is enabled for you!</p>
{% else %}
    <p>Foo is disabled for you.</p>
{% endif %}
```

Or in Python:

```python
import flags


print(flags.FooEnabled(user).value)
```

## Installation

```python
INSTALLED_PACKAGES = [
    ...
    "plain.flags",
]
```

Create a `flags.py` at the top of your `app` (or point `settings.FLAGS_MODULE` to a different location).

## Advanced usage

Ultimately you can do whatever you want inside of `get_key` and `get_value`.

```python
class OrganizationFeature(Flag):
    url_param_name = ""

    def __init__(self, request=None, organization=None):
        # Both of these are optional, but will usually both be given
        self.request = request
        self.organization = organization

    def get_key(self):
        if (
            self.url_param_name
            and self.request
            and self.url_param_name in self.request.query_params
        ):
            return None

        if not self.organization:
            # Don't save the flag result for PRs without an organization
            return None

        return self.organization

    def get_value(self):
        if self.url_param_name and self.request:
            if self.request.query_params.get(self.url_param_name) == "1":
                return True

            if self.request.query_params.get(self.url_param_name) == "0":
                return False

        if not self.organization:
            return False

        # All organizations will start with False,
        # and I'll override in the DB for the ones that should be True
        return False


class AIEnabled(OrganizationFeature):
    pass

```
