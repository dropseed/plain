"""DetailView / ListView — both Schema-agnostic. CreateView, UpdateView,
and DeleteView (Form-based) have been removed in favor of
SchemaCreateView / SchemaUpdateView / SchemaDeleteView in views/schema.py."""

from abc import ABC, abstractmethod
from typing import Any

from plain.http import NotFoundError404

try:
    from plain.postgres.exceptions import ObjectDoesNotExist
except ImportError:
    ObjectDoesNotExist = None  # ty: ignore[invalid-assignment]

from .templates import TemplateView

# Sentinel for the per-instance object/objects cache. Not exported.
_UNSET: Any = object()


class DetailView[M = Any](TemplateView, ABC):
    """Render a "detail" view of an object.

    By default this is a model instance looked up from `self.get_object()`, but
    the view will support display of *any* object by overriding `get_object()`.

    Generic over the object type — subclasses that want type-safe access to
    `self.object` should parameterize: `class TaskDetail(DetailView[Task])`.
    `M` defaults to `Any` so unparameterized usage stays ergonomic.

    Implementation note: uses `@property` + manual instance caching rather
    than `@cached_property` because ty doesn't currently propagate generics
    through `cached_property` descriptors. The runtime semantics are
    identical (resolved once per instance, then cached).
    """

    context_object_name = ""

    @property
    def object(self) -> M:
        cached = self.__dict__.get("_object_cache", _UNSET)
        if cached is not _UNSET:
            return cached
        try:
            obj = self.get_object()
        except Exception as e:
            # If ObjectDoesNotExist is available and this is that exception, raise 404
            if ObjectDoesNotExist and isinstance(e, ObjectDoesNotExist):
                raise NotFoundError404
            # Otherwise, let other exceptions bubble up
            raise

        # Also raise 404 if get_object() returns None / falsy
        if not obj:
            raise NotFoundError404

        self.__dict__["_object_cache"] = obj
        return obj

    @abstractmethod
    def get_object(self) -> M | None: ...

    def get_template_context(self) -> dict[str, Any]:
        """Insert the single object into the context dict."""
        context = super().get_template_context()
        context["object"] = self.object
        if self.context_object_name:
            context[self.context_object_name] = self.object
        return context


class ListView[M = Any](TemplateView, ABC):
    """Render a list of objects from `self.get_objects()`, with a response
    rendered by a template.

    Generic over the object type — `class TaskListView(ListView[Task])`
    types `self.objects: list[Task]`. `M` defaults to `Any`.

    See `DetailView` re: `@property` + manual caching for ty compatibility.
    """

    context_object_name = ""

    @property
    def objects(self) -> list[M]:
        cached = self.__dict__.get("_objects_cache", _UNSET)
        if cached is not _UNSET:
            return cached
        objs = self.get_objects()
        self.__dict__["_objects_cache"] = objs
        return objs

    @abstractmethod
    def get_objects(self) -> list[M]: ...

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["objects"] = self.objects
        if self.context_object_name:
            context[self.context_object_name] = self.objects
        return context
