# plain.api

**Build APIs using class-based views.**

The `plain.api` package provides lightweight view classes for building APIs using the same patterns as regular views. It also provides an `APIKey` model and support for generating [OpenAPI](https://www.openapis.org/) documents.

```python
# app/api/views.py
from plain.api.views import APIKeyView, APIView
from plain.http import JsonResponse
from plain.views.exeptions import ResponseException

from app.users.models import User
from app.pullrequests.models import PullRequest


class BaseAPIView(APIView, APIKeyView):
    def use_api_key(self, api_key):
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


class UserView(BaseAPIView):
    def get(self) -> User:
        return {
            "uuid": self.request.user.uuid,
            "username": self.request.user.username,
            "time_zone": str(self.request.user.time_zone),
        }


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
user.api_key = APIKey.objects.create(name="Example")
user.save()
```

If your API key is associated with something other than a user, or does not use the related name `"users"`, you can define your own [`associate_api_key`](./views.py#associate_api_key) method.

## OpenAPI

TODO
