"""DetailView / ListView — both Schema-agnostic. CreateView, UpdateView,
and DeleteView (Form-based) have been removed in favor of
SchemaCreateView / SchemaUpdateView / SchemaDeleteView in views/schema.py."""

from abc import ABC, abstractmethod
from functools import cached_property
from typing import Any

from plain.http import NotFoundError404

try:
    from plain.postgres.exceptions import ObjectDoesNotExist
except ImportError:
    ObjectDoesNotExist = None  # ty: ignore[invalid-assignment]

from .templates import TemplateView


class DetailView(TemplateView, ABC):
    """Render a "detail" view of an object.

    By default this is a model instance looked up from `self.get_object()`, but
    the view will support display of *any* object by overriding `get_object()`.
    """

    context_object_name = ""

    @cached_property
    def object(self) -> Any:
        try:
            obj = self.get_object()
        except Exception as e:
            # If ObjectDoesNotExist is available and this is that exception, raise 404
            if ObjectDoesNotExist and isinstance(e, ObjectDoesNotExist):
                raise NotFoundError404
            # Otherwise, let other exceptions bubble up
            raise

        # Also raise 404 if get_object() returns None
        if not obj:
            raise NotFoundError404

        return obj

    @abstractmethod
    def get_object(self) -> Any: ...

    def get_template_context(self) -> dict[str, Any]:
        """Insert the single object into the context dict."""
        context = super().get_template_context()
        context["object"] = self.object
        if self.context_object_name:
            context[self.context_object_name] = self.object
        return context


class ListView(TemplateView, ABC):
    """Render a list of objects from `self.get_objects()`, with a response
    rendered by a template."""

    context_object_name = ""

    @cached_property
    def objects(self) -> Any:
        return self.get_objects()

    @abstractmethod
    def get_objects(self) -> Any: ...

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["objects"] = self.objects
        if self.context_object_name:
            context[self.context_object_name] = self.objects
        return context
