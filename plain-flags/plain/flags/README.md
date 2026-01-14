# plain.flags

**Local feature flags via database models.**

- [Overview](#overview)
- [Usage in templates](#usage-in-templates)
- [Usage in Python](#usage-in-python)
- [Advanced usage](#advanced-usage)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You write custom flags as subclasses of [`Flag`](./flags.py#Flag).
Each flag defines a "key" (to identify who/what the flag applies to) and an initial value.
The results are stored in the database, allowing you to override them later via the admin.

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

To check a flag, import it and access the `.value` property:

```python
from app import flags

if flags.FooEnabled(user).value:
    # Feature is enabled for this user
    ...
```

You can also use flags directly in boolean expressions since they implement `__bool__`:

```python
if flags.FooEnabled(user):
    # Feature is enabled
    ...
```

## Usage in templates

You can use flags directly in HTML templates:

```html
{% if flags.FooEnabled(get_current_user()) %}
    <p>Foo is enabled for you!</p>
{% else %}
    <p>Foo is disabled for you.</p>
{% endif %}
```

## Usage in Python

```python
from app import flags


# Check as a boolean
if flags.FooEnabled(user):
    print("Foo is enabled!")

# Get the actual value
print(flags.FooEnabled(user).value)
```

## Advanced usage

You can do whatever you want inside of `get_key` and `get_value`. For example, you might want to check URL parameters to temporarily enable a feature during development:

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

## FAQs

#### How do flags get stored in the database?

When you first use a flag, plain.flags creates a [`Flag`](./models.py#Flag) record in the database to track the flag itself, and a [`FlagResult`](./models.py#FlagResult) record for each unique key. The `FlagResult` stores the computed value so subsequent calls return the cached result.

#### How do I override a flag value?

You can modify flag results directly in the database or through the admin interface. Each `FlagResult` has a `value` field that you can update to override the computed value.

#### What if I want to temporarily compute the value without storing it?

Return a falsy value (like `None`) from `get_key()`. When there's no key, the flag will compute the value fresh each time without storing it in the database.

#### How do I disable a flag entirely?

Each [`Flag`](./models.py#Flag) record has an `enabled` field. Set it to `False` to disable the flag. In debug mode, accessing a disabled flag raises a [`FlagDisabled`](./exceptions.py#FlagDisabled) exception. In production, it logs an error and returns `None`.

## Installation

Install the `plain.flags` package from [PyPI](https://pypi.org/project/plain.flags/):

```bash
uv add plain.flags
```

Add to your `INSTALLED_PACKAGES`:

```python
INSTALLED_PACKAGES = [
    ...
    "plain.flags",
]
```

Create a `flags.py` at the top of your `app` (or point `settings.FLAGS_MODULE` to a different location).
