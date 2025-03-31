# plain.api

**Build APIs using class-based views.**

The `plain.api` package provides lightweight view classes for building APIs using the same patterns as regular views. It also provides an `APIKey` model and support for generating [OpenAPI](https://www.openapis.org/) documents.

Here's a basic example of using [`APIObjectView`](./views#APIObjectView):

```python
# app/api/views.py
from plain.api.views import APIAuthViewMixin, APIObjectView

from app.users.models import User
from app.pullrequests.models import PullRequest


class UserView(APIAuthViewMixin, APIObjectView):
    allowed_http_methods = ["get"]

    def get_object(self) -> User:
        return self.request.user

    def object_to_dict(self, obj: User):
        return {
            "uuid": obj.uuid,
            "username": obj.username,
            "time_zone": str(obj.time_zone),
        }


class PullRequestView(APIAuthViewMixin, APIObjectView):
    allowed_http_methods = ["get"]

    def get_object(self) -> PullRequest:
        return (
            PullRequest.objects.all()
            .visible_to_user(self.request.user)
            .get(uuid=self.url_kwargs["uuid"])
        )

    def object_to_dict(self, obj: PullRequest):
        return {
            "uuid": obj.uuid,
            "state": obj.state,
            "number": obj.number,
            "host_url": obj.host_url,
            "host_created_at": obj.host_created_at,
            "host_updated_at": obj.host_updated_at,
            "host_merged_at": obj.host_merged_at,
            "author": {
                "uuid": obj.author.uuid,
                "display_name": obj.author.display_name,
            },
        }
```

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

The [`APIAuthViewMixin`](./views.py#APIAuthViewMixin) is an extension of [`plain.auth.views.AuthViewMixin`](/plain-auth/plain/auth/views.py#AuthViewMixin) that uses the `Authorization: Bearer {apikey}` header to authenticate requests.

To check whether a user can access an endpoint, typically you will use the `request.user` when performing `get_object` (or `get_objects`) to only return objects they have access to. If an object is not returned, a 404 response will be returned instead.

```python
class PullRequestView(APIAuthViewMixin, APIObjectView):
    allowed_http_methods = ["get"]

    def get_object(self) -> PullRequest:
        return (
            PullRequest.objects.all()
            .visible_to_user(self.request.user)  # Filter the queryset
            .get(uuid=self.url_kwargs["uuid"])
        )
```

Other permission checks can be done through the `check_auth()` method provided by `AuthViewMixin`, or the specific `get`, `post`, `put`, `patch`, or `delete` method on the view.

```python
class SuperAdminView(APIAuthViewMixin, APIObjectView):
    allowed_http_methods = ["get"]

    def check_auth(self):
        super().check_auth()

        if not self.request.user.is_super_admin:
            raise PermissionDenied("You are not allowed to access this resource.")
```

## Object lists

TODO

## Forms

TODO

## API keys

The provided [`APIKey` model](./models.py) includes randomly generated, unique API tokens that are automatically parsed by `APIAuthViewMixin`. The tokens can optionally be named and include an `expires_at` date.

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

    def __str__(self):
        return self.username
```

Generating API keys is something you will need to do in your own code, wherever it makes sense to do so.

```python
user = User.objects.first()
user.api_key = APIKey.objects.create(name="Example")
user.save()
```

If your API key is associated with something other than a user, or does not use the related name `"users"`, you can define your own [`associate_api_key`](./views.py#associate_api_key) method.

## OpenAPI

TODO
