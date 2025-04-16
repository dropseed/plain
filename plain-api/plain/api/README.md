# plain.api

**Build APIs using class-based views.**

This package includes lightweight view classes for building APIs using the same patterns as regular HTML views. It also provides an [`APIKey` model](#api-keys) and support for generating [OpenAPI](#openapi) documents.

Because [Views](/plain/plain/views/README.md) can convert built-in types to responses, an API view can simply return a dict or list to send a JSON response back to the client. More complex responses can use the [`JsonResponse`](/plain/plain/http/response.py#JsonResponse) class.

```python
# app/api/views.py
from plain.api.views import APIKeyView, APIView
from plain.http import JsonResponse
from plain.views.exeptions import ResponseException

from app.users.models import User
from app.pullrequests.models import PullRequest


# An example base class that will be used across your custom API
class BaseAPIView(APIView, APIKeyView):
    def use_api_key(self):
        super().use_api_key()

        if user := self.api_key.users.first():
            self.request.user = user
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
        return {
            "uuid": self.request.user.uuid,
            "username": self.request.user.username,
            "time_zone": str(self.request.user.time_zone),
        }


# An endpoint that filters querysets based on the user
class PullRequestView(BaseAPIView):
    def get(self):
        try:
            pull = (
                PullRequest.objects.all()
                .visible_to_user(self.request.user)
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
        super().use_api_key()

        if user := self.api_key.users.first():
            self.request.user = user
        else:
            raise ResponseException(
                JsonResponse(
                    {"error": "API key not associated with a user."},
                    status_code=403,
                )
            )
```

When it comes to authorizing actions, typically you will factor this in to the queryset to only return objects that the user is allowed to see. If a response method (`get`, `post`, etc.) returns `None`, then the view will return a 404 response. Other status codes can be returned with an int (ex. `403`) or a `JsonResponse` object.

```python
class PullRequestView(BaseAPIView):
    def get(self):
        try:
            pull = (
                PullRequest.objects.all()
                .visible_to_user(self.request.user)
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
    class Meta:
        model = User
        fields = [
            "username",
            "time_zone",
        ]

class UserView(BaseAPIView):
    def patch(self):
        form = UserForm(
            request=self.request,
            instance=self.request.user,
        )

        if form.is_valid():
            user = form.save()
            return {
                "uuid": user.uuid,
                "username": user.username,
                "time_zone": str(user.time_zone),
            }
        else:
            return {"errors": form.errors}
```

If you don't want to use Plain's forms, you could also use a third-party schema/validation library like [Pydantic](https://docs.pydantic.dev/latest/) or [Marshmallow](https://marshmallow.readthedocs.io/en/3.x-line/). But depending on your use case, you may not need to use forms or fancy validation at all!

## `DELETE`

Deletes can be handled in the `delete` method of the view. Most of the time this just means getting the object, deleting it, and returning a 204.

```python
class PullRequestView(BaseAPIView):
    def delete(self):
        try:
            pull = (
                PullRequest.objects.all()
                .visible_to_user(self.request.user)
                .get(uuid=self.url_kwargs["uuid"])
            )
        except PullRequest.DoesNotExist:
            return None

        pull.delete()

        return 204
```

## API keys

The provided [`APIKey` model](./models.py) includes randomly generated, unique API tokens that are automatically parsed by `APIKeyView`. The tokens can optionally be named and include an `expires_at` date.

Associating an `APIKey` with a user (or team, for example) is up to you. Most likely you will want to use a `ForeignKey` or a `ManyToManyField`.

```python
# app/users/models.py
from plain import models
from plain.api.models import APIKey


@models.register_model
class User(models.Model):
    # other fields...
    api_key = models.ForeignKey(
        APIKey,
        on_delete=models.CASCADE,
        related_name="users",
        allow_null=True,
        required=False,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["api_key"],
                condition=models.Q(api_key__isnull=False),
                name="unique_user_api_key",
            ),
        ]
```

Generating API keys is something you will need to do in your own code, wherever it makes sense to do so.

```python
user = User.objects.first()
user.api_key = APIKey.objects.create()
user.save()
```

To use API keys in your views, you can inherit from `APIKeyView` and customize the [`use_api_key` method](./views.py#use_api_key) to set the `request.user` attribute (or any other attribute) to the object associated with the API key.

```python
# app/api/views.py
from plain.api.views import APIKeyView, APIView


class BaseAPIView(APIView, APIKeyView):
    def use_api_key(self):
        super().use_api_key()

        if user := self.api_key.users.first():
            self.request.user = user
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
        if self.request.user:
            user = self.request.user
        else:
            raise Http404

        return schemas.UserSchema.from_user(user, self.request)
```

While you can attach any raw schema you like, there are a couple helpers to generate schema for API input (`@openapi.request_form`) and output (`@openapi.response_typed_dict`). These are intentionally specific, leaving room for custom decorators to be written for the input/output types of your choice.

```python
class TeamAccountAPIView(BaseAPIView):
    @openapi.request_form(TeamAccountForm)
    @openapi.response_typed_dict(200, TeamAccountSchema)
    def patch(self):
        form = TeamAccountForm(request=self.request, instance=self.team_account)

        if form.is_valid():
            team_account = form.save()
            return TeamAccountSchema.from_team_account(
                team_account, self.request
            )
        else:
            return {"errors": form.errors}

    @cached_property
    def team_account(self):
        try:
            if self.organization:
                return TeamAccount.objects.get(
                    team__organization=self.organization, uuid=self.url_kwargs["uuid"]
                )

            if self.request.user:
                return TeamAccount.objects.get(
                    team__organization__in=self.request.user.organizations.all(),
                    uuid=self.url_kwargs["uuid"],
                )
        except TeamAccount.DoesNotExist:
            raise Http404


class TeamAccountForm(ModelForm):
    class Meta:
        model = TeamAccount
        fields = ["is_reviewer", "is_admin"]


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

To generate the OpenAPI JSON, run the following command (including swagger.io validation):

```bash
plain api generate-openapi --validate
```

### Deploying

To build the JSON when you deploy, add a `build.run` command to your `pyproject.toml` file:

```toml
[tool.plain.build.run]
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
