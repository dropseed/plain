from abc import ABC, abstractmethod
from functools import cached_property
from typing import Any

from plain.exceptions import ImproperlyConfigured

try:
    from plain.models.exceptions import ObjectDoesNotExist
except ImportError:
    ObjectDoesNotExist = None  # type: ignore[misc, assignment]

from plain.forms import BaseForm, Form
from plain.http import NotFoundError404

from .forms import FormView
from .templates import TemplateView


class CreateView(FormView):
    """
    View for creating a new object, with a response rendered by a template.
    """

    # TODO? would rather you have to specify this...
    def get_success_url(self, form: BaseForm) -> str:
        """Return the URL to redirect to after processing a valid form."""
        if self.success_url:
            url = str(self.success_url).format(**self.object.__dict__)
        else:
            try:
                url = self.object.get_absolute_url()
            except AttributeError:
                raise ImproperlyConfigured(
                    "No URL to redirect to.  Either provide a url or define"
                    " a get_absolute_url method on the Model."
                )
        return url

    def form_valid(self, form: BaseForm) -> Any:
        """If the form is valid, save the associated model."""
        self.object = form.save()  # type: ignore[attr-defined]
        return super().form_valid(form)


class DetailView(TemplateView, ABC):
    """
    Render a "detail" view of an object.

    By default this is a model instance looked up from `self.queryset`, but the
    view will support display of *any* object by overriding `self.get_object()`.
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
        context["object"] = (
            self.object
        )  # Some templates can benefit by always knowing a primary "object" can be present
        if self.context_object_name:
            context[self.context_object_name] = self.object
        return context


class UpdateView(DetailView, FormView):
    """View for updating an object, with a response rendered by a template."""

    def get_success_url(self, form: BaseForm) -> str:
        """Return the URL to redirect to after processing a valid form."""
        if self.success_url:
            url = str(self.success_url).format(**self.object.__dict__)
        else:
            try:
                url = self.object.get_absolute_url()
            except AttributeError:
                raise ImproperlyConfigured(
                    "No URL to redirect to.  Either provide a url or define"
                    " a get_absolute_url method on the Model."
                )
        return url

    def form_valid(self, form: BaseForm) -> Any:
        """If the form is valid, save the associated model."""
        form.save()  # type: ignore[attr-defined]
        return super().form_valid(form)

    def get_form_kwargs(self) -> dict[str, Any]:
        """Return the keyword arguments for instantiating the form."""
        kwargs = super().get_form_kwargs()
        kwargs.update({"instance": self.object})
        return kwargs


class DeleteView(DetailView, FormView):
    """
    View for deleting an object retrieved with self.get_object(), with a
    response rendered by a template.
    """

    class EmptyDeleteForm(Form):
        def __init__(self, instance: Any, **kwargs: Any) -> None:
            self.instance = instance
            super().__init__(**kwargs)

        def save(self) -> None:
            self.instance.delete()

    form_class = EmptyDeleteForm

    def get_form_kwargs(self) -> dict[str, Any]:
        """Return the keyword arguments for instantiating the form."""
        kwargs = super().get_form_kwargs()
        kwargs.update({"instance": self.object})
        return kwargs

    def form_valid(self, form: BaseForm) -> Any:
        """If the form is valid, save the associated model."""
        form.save()  # type: ignore[attr-defined]
        return super().form_valid(form)


class ListView(TemplateView, ABC):
    """
    Render some list of objects, set by `self.get_queryset()`, with a response
    rendered by a template.
    """

    context_object_name = ""

    @cached_property
    def objects(self) -> Any:
        return self.get_objects()

    @abstractmethod
    def get_objects(self) -> Any: ...

    def get_template_context(self) -> dict[str, Any]:
        """Insert the single object into the context dict."""
        context = super().get_template_context()
        context["objects"] = self.objects
        if self.context_object_name:
            context[self.context_object_name] = self.objects
        return context
