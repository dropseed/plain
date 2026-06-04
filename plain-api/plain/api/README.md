# plain.api

**Build APIs using class-based views.**

- [Overview](#overview)
- [Authentication and authorization](#authentication-and-authorization)
- [`PUT`, `POST`, and `PATCH`](#put-post-and-patch)
- [`DELETE`](#delete)
- [API keys](#api-keys)
- [OpenAPI](#openapi)
    - [Deploying](#deploying)
- [Settings](#settings)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

This package includes lightweight view classes for building APIs using the same patterns as regular HTML views. It also provides an [`APIKey`](./models.py#APIKey) model and support for generating [OpenAPI](#openapi) documents.

`APIView` accepts shorthand return types — return a dict or list and it's converted to a `JsonResponse`. (The base `View` only accepts `Response` objects; this coercion is specific to `APIView`.)

```python
# app/api/views.py
from plain.api.views import APIView


class HelloWorldView(APIView):
    def get(self):
        return {"message": "Hello, world!"}
```

More complex responses can use the [`JsonResponse`](/plain/plain/http/response.py#JsonResponse) class, and you can return a status code with the response body by returning a tuple of `(status_code, data)` (ex. `return 201, {...}`).

Here is a more complete example that shows how to build a custom API with authentication and authorization:

```python
# app/api/views.py
from plain.api.views import APIKeyView, APIView
from plain.auth import get_request_user, set_request_user
from plain.http import JsonResponse
from plain.views.exceptions import ResponseException

from app.users.models import User
from app.pullrequests.models import PullRequest


# An example base class that will be used across your custom API
class BaseAPIView(APIView, APIKeyView):
    def use_api_key(self):
        super().use_api_key()

        if user := User.query.filter(api_key=self.api_key).first():
            set_request_user(self.request, user)
        else:
            raise ResponseException(
                JsonResponse(
                    {"error": "API key not associated with a user."},
                    status_code=403,
                )
            )


# An endpoint that returns the current user
class UserView(BaseAPIView):
    def get(self):
        user = get_request_user(self.request)
        return {
            "uuid": user.uuid,
            "username": user.username,
            "time_zone": str(user.time_zone),
        }


# An endpoint that filters querysets based on the user
class PullRequestView(BaseAPIView):
    def get(self):
        try:
            pull = (
                PullRequest.query.all()
                .visible_to_user(get_request_user(self.request))
                .get(uuid=self.url_kwargs["uuid"])
            )
        except PullRequest.DoesNotExist:
            return None

        return {
            "uuid": pull.uuid,
            "state": pull.state,
            "number": pull.number,
            "host_url": pull.host_url,
            "host_created_at": pull.host_created_at,
            "host_updated_at": pull.host_updated_at,
            "host_merged_at": pull.host_merged_at,
            "author": {
                "uuid": pull.author.uuid,
                "display_name": pull.author.display_name,
            },
        }
```

URLs work like they do everywhere else, though it's generally recommended to put everything together into an `app.api` package and `api` namespace.

```python
# app/api/urls.py
from plain.urls import Router, path

from . import views


class APIRouter(Router):
    namespace = "api"
    urls = [
        path("user/", views.UserView),
        path("pullrequests/<uuid:uuid>/", views.PullRequestView),
    ]
```

## Authentication and authorization

Handling authentication in the API is pretty straightforward. If you use [API keys](#api-keys), then the `APIKeyView` will parse the `Authorization: Bearer <token>` header and set `self.api_key`. You will then customize the `use_api_key` method to associate the request with a user (or team, for example), depending on how your app works.

```python
class BaseAPIView(APIView, APIKeyView):
    def use_api_key(self):
        from plain.auth import get_request_user, set_request_user
        from app.users.models import User

        super().use_api_key()

        if user := User.query.filter(api_key=self.api_key).first():
            set_request_user(self.request, user)
        else:
            raise ResponseException(
                JsonResponse(
                    {"error": "API key not associated with a user."},
                    status_code=403,
                )
            )
```

When it comes to authorizing actions, typically you will factor this in to the queryset to only return objects that the user is allowed to see. If a response method (`get`, `post`, etc.) returns `None`, then the view will return a 404 response. Other status codes can be returned by raising an HTTP exception (ex. `raise ForbiddenError403`) or by returning a `Response`/`JsonResponse` directly.

```python
class PullRequestView(BaseAPIView):
    def get(self):
        from plain.auth import get_request_user

        try:
            pull = (
                PullRequest.query.all()
                .visible_to_user(get_request_user(self.request))
                .get(uuid=self.url_kwargs["uuid"])
            )
        except PullRequest.DoesNotExist:
            return None

        # ...return the authorized data here
```

## `PUT`, `POST`, and `PATCH`

One way to handle PUT, POST, and PATCH endpoints is to use standard [forms](/plain/plain/forms/README.md). This will use the same validation and error handling as an HTML form, but will parse the input from the JSON request instead of HTML form data.

```python
class UserForm(ModelForm):
    username = model_field(User.username)
    time_zone = model_field(User.time_zone)


class UserView(BaseAPIView):
    def patch(self):
        from plain.auth import get_request_user

        user = get_request_user(self.request)
        result = UserForm.validate(self.request.json_data)
        if not result:
            return 400, {
                "errors": [
                    {"field": e.field, "code": e.code, "message": e.message}
                    for e in result.errors
                ]
            }

        update_from(user, result)
        return {
            "uuid": user.uuid,
            "username": user.username,
            "time_zone": str(user.time_zone),
        }
```

If you don't want to use Plain's forms, you could also use a third-party schema/validation library like [Pydantic](https://docs.pydantic.dev/latest/) or [Marshmallow](https://marshmallow.readthedocs.io/en/3.x-line/). But depending on your use case, you may not need to use forms or fancy validation at all!

## `DELETE`

Deletes can be handled in the `delete` method of the view. Most of the time this just means getting the object, deleting it, and returning a 204.

```python
from plain.http import Response


class PullRequestView(BaseAPIView):
    def delete(self):
        from plain.auth import get_request_user

        try:
            pull = (
                PullRequest.query.all()
                .visible_to_user(get_request_user(self.request))
                .get(uuid=self.url_kwargs["uuid"])
            )
        except PullRequest.DoesNotExist:
            return None

        pull.delete()

        return Response(status_code=204)
```

## API keys

The provided [`APIKey`](./models.py#APIKey) model includes randomly generated, unique API tokens that are automatically parsed by `APIKeyView`. The tokens can optionally be named and include an `expires_at` date.

Associating an `APIKey` with a user (or team, for example) is up to you. Most likely you will want to use a `ForeignKey` or a `ManyToManyField`.

```python
# app/users/models.py
from plain import postgres
from plain.postgres import types
from plain.api.models import APIKey


@postgres.register_model
class User(postgres.Model):
    # other fields...
    api_key: APIKey = types.ForeignKeyField(
        APIKey,
        on_delete=postgres.CASCADE,
        allow_null=True,
        required=False,
    )

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["api_key"],
                condition=postgres.Q(api_key__isnull=False),
                name="unique_user_api_key",
            ),
        ],
    )
```

Generating API keys is something you will need to do in your own code, wherever it makes sense to do so.

```python
user = User.query.first()
user.api_key = APIKey.query.create()
user.update()
```

To use API keys in your views, you can inherit from `APIKeyView` and customize the [`use_api_key`](./views.py#use_api_key) method to associate the request with a user (or any other object) using `set_request_user()`.

```python
# app/api/views.py
from plain.api.views import APIKeyView, APIView
from plain.auth import set_request_user
from plain.views.exceptions import ResponseException

from app.users.models import User


class BaseAPIView(APIView, APIKeyView):
    def use_api_key(self):
        super().use_api_key()

        if user := User.query.filter(api_key=self.api_key).first():
            set_request_user(self.request, user)
        else:
            raise ResponseException(
                JsonResponse(
                    {"error": "API key not associated with a user."},
                    status_code=403,
                )
            )
```

## OpenAPI

You can use a combination of decorators to help generate an [OpenAPI](https://www.openapis.org/) document for your API.

To define root level schema, use the `@openapi.schema` decorator on your `Router` class.

```python
from plain.urls import Router, path
from plain.api import openapi
from plain.assets.views import AssetView
from . import views


@openapi.schema({
    "openapi": "3.0.0",
    "info": {
        "title": "PullApprove API",
        "version": "4.0.0",
    },
    "servers": [
        {
            "url": "https://4.pullapprove.com/api/",
            "description": "PullApprove API",
        }
    ],
})
class APIRouter(Router):
    namespace = "api"
    urls = [
        # ...your API routes
    ]
```

You can then define additional schema on a view class, or a specific view method.

```python
class CurrentUserAPIView(BaseAPIView):
    @openapi.schema({
        "summary": "Get current user",
    })
    def get(self):
        from plain.auth import get_request_user

        user = get_request_user(self.request)
        if not user:
            raise NotFoundError404

        return schemas.UserSchema.from_user(user, self.request)
```

### Helpers for the boilerplate parts

Most of an OpenAPI dict is the same envelope repeated. `plain.api.openapi` ships small helpers so you can focus on the schemas:

- `openapi.json_content(schema)` → wraps a schema in `application/json`
- `openapi.json_body(schema, *, required=True)` → builds a full `application/json` requestBody
- `openapi.link_to(view_class, *, parameters, method="get")` → builds an OpenAPI `link` to another view's operation, using the framework-default operationId

```python
@openapi.schema({
    "requestBody": openapi.json_body({"$ref": "#/components/schemas/NoteInput"}),
    "responses": {
        "201": {
            "description": "The created note.",
            "content": openapi.json_content({"$ref": "#/components/schemas/Note"}),
            "links": {
                "GetById": openapi.link_to(
                    NoteDetailAPIView, parameters={"id": "$response.body#/id"}
                ),
            },
        },
    },
})
def post(self):
    ...
```

### What the generator emits for you

Things you don't have to declare yourself:

- **`operationId`** — defaults to `{ViewClassName}_{method}` (e.g. `NoteDetailAPIView_get`). Override per-operation via `@openapi.schema({"operationId": "..."})`.
- **`components.schemas.ErrorSchema`** + the shared `BadRequest` / `Unauthorized` / `Forbidden` / `NotFound` / `ServerError` `responses` — every `APIView` operation auto-attaches the matching `$ref` for those status codes.
- **`securitySchemes.BearerAuth`** + per-operation `security: [{BearerAuth: []}]` — auto-emitted whenever a view inherits from `APIKeyView`. Subclasses can override `openapi_security_schemes` to declare a different scheme.
- **Native types for path converters** — `<int:>` becomes `type: integer`, `<uuid:>` becomes `type: string, format: uuid`.

### Custom input/output schema

For more involved schema generation, there are a couple of decorators (`@openapi.request_form`, `@openapi.response_typed_dict`). These are intentionally specific, leaving room for custom decorators to be written for the input/output types of your choice.

```python
class TeamAccountAPIView(BaseAPIView):
    @openapi.request_form(TeamAccountForm)
    @openapi.response_typed_dict(200, TeamAccountSchema)
    def patch(self):
        result = TeamAccountForm.validate(self.request.json_data)
        if not result:
            return 400, {
                "errors": [
                    {"field": e.field, "code": e.code, "message": e.message}
                    for e in result.errors
                ]
            }

        update_from(self.team_account, result)
        return TeamAccountSchema.from_team_account(
            self.team_account, self.request
        )

    @cached_property
    def team_account(self):
        try:
            if self.organization:
                return TeamAccount.query.get(
                    team__organization=self.organization, uuid=self.url_kwargs["uuid"]
                )

            user = get_request_user(self.request)
            if user:
                return TeamAccount.query.get(
                    team__organization__in=user.organizations.all(),
                    uuid=self.url_kwargs["uuid"],
                )
        except TeamAccount.DoesNotExist:
            raise NotFoundError404


class TeamAccountForm(ModelForm):
    is_reviewer = model_field(TeamAccount.is_reviewer)
    is_admin = model_field(TeamAccount.is_admin)


class TeamAccountSchema(TypedDict):
    uuid: UUID
    account: AccountSchema
    is_admin: bool
    is_reviewer: bool
    api_url: str

    @classmethod
    def from_team_account(cls, team_account, request) -> "TeamAccountSchema":
        return cls(
            uuid=team_account.uuid,
            is_admin=team_account.is_admin,
            is_reviewer=team_account.is_reviewer,
            api_url=request.build_absolute_uri(
                reverse("api:team_account", uuid=team_account.uuid)
            ),
            account=AccountSchema.from_account(team_account.account, request),
        )
```

To generate the OpenAPI JSON, run the following command:

```bash
plain api generate-openapi --validate
```

`--validate` runs the generated schema through [`openapi-spec-validator`](https://pypi.org/project/openapi-spec-validator/) locally — no network calls. Install it as a dev dependency to use the flag:

```bash
uv add --dev openapi-spec-validator
```

### Deploying

To build the JSON when you deploy, add a build command to your `pyproject.toml` file:

```toml
[tool.plain.assets.run]
openapi = {cmd = "plain api generate-openapi --validate > app/assets/openapi.json"}
```

You will typically want `app/assets/openapi.json` to be included in your `.gitignore` file.

Then you can use an [`AssetView`](/plain/plain/assets/views.py#AssetView) to serve the `openapi.json` file.

```python
from plain.urls import Router, path
from plain.assets.views import AssetView
from . import views

class APIRouter(Router):
    namespace = "api"
    urls = [
        # ...your API routes
        path("openapi.json", AssetView.as_view(asset_path="openapi.json")),
    ]
```

## Settings

| Setting              | Default | Env var                    |
| -------------------- | ------- | -------------------------- |
| `API_OPENAPI_ROUTER` | `""`    | `PLAIN_API_OPENAPI_ROUTER` |

See [`default_settings.py`](./default_settings.py) for more details.

## FAQs

#### How do I return JSON 404s for unmatched paths under `/api/`?

Plain's default 404 handler renders an HTML page. To return a JSON `ErrorSchema` body for unmatched paths under your API prefix, mount [`JsonNotFoundView`](./views.py#JsonNotFoundView) as a regex catch-all at the end of your API router:

```python
import re
from plain.api.views import JsonNotFoundView
from plain.urls import Router, path


class APIRouter(Router):
    namespace = "api"
    urls = [
        # ...your API routes
        path(re.compile(r"^[\s\S]+$"), JsonNotFoundView, name="not_found"),
    ]
```

#### How do I make an API key optional?

You can set `api_key_required = False` on your view class to make API key authentication optional. The `self.api_key` will be `None` if no valid key is provided.

```python
class PublicAPIView(APIView, APIKeyView):
    api_key_required = False

    def get(self):
        if self.api_key:
            # Authenticated request
            return {"status": "authenticated"}
        else:
            # Anonymous request
            return {"status": "anonymous"}
```

#### Can I use plain.api without plain.postgres?

Yes. The `APIKey` model requires `plain.postgres`, but you can use `APIView` without it. If you try to use `APIKeyView` without `plain.postgres` installed, you will need to override the [`get_api_key`](./views.py#get_api_key) method to provide your own API key lookup logic.

#### How do I return different status codes?

You can return status codes in several ways:

- Return a tuple of `(status_code, data)`: `return 201, {"id": note.id}`
- Return `None`: automatically returns 404
- Return a `Response` with a custom status code: `return Response(status_code=204)` (for no content)
- Return a `JsonResponse` with a custom status code: `return JsonResponse({"error": "Bad request"}, status_code=400)`
- Raise an exception: `raise NotFoundError404` or `raise ForbiddenError403`

#### How do I access the request body?

You can access the parsed JSON body using `self.request.json()`. For form data, use `self.request.POST`.

```python
class CreateItemView(APIView):
    def post(self):
        data = self.request.json()
        name = data.get("name")
        return {"created": name}
```

## Installation

Install the `plain.api` package from [PyPI](https://pypi.org/project/plain.api/):

```console
uv add plain.api
```

Typically you will want to create an `api` package to contain all of the views and URLs for your app's API.

```console
plain create api
```

The `app.api` package should be added to your app's `INSTALLED_APPS` setting in `app/settings.py`:

```python
# app/settings.py
INSTALLED_APPS = [
    # ...other apps
    "app.api",
]
```

Then create a your API URL router and your first API view.

```python
# app/api/urls.py
from plain.urls import Router, path
from plain.api.views import APIView


class ExampleAPIView(APIView):
    def get(self):
        return {"message": "Hello, world!"}


class APIRouter(Router):
    namespace = "api"
    urls = [
        path("example/", ExampleAPIView),
    ]
```

The `APIRouter` can then be included in your app's URLs.

```python
# app/urls.py
from plain.urls import include, path

from .api.urls import APIRouter


class AppRouter(Router):
    namespace = "app"
    urls = [
        # ...other routes
        include("api/", APIRouter),
    ]
```
