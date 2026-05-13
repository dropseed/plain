from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from functools import cached_property
from typing import Any, NoReturn

from plain.exceptions import ImproperlyConfigured
from plain.forms import BaseForm, Form
from plain.http import HTTPException, NotFoundError404, RedirectResponse, Response
from plain.logs import get_framework_logger
from plain.runtime import settings
from plain.views import View

from .core import Template, TemplateFileMissing

logger = get_framework_logger("plain.templates")

try:
    from plain.postgres.exceptions import ObjectDoesNotExist
except ImportError:
    ObjectDoesNotExist = None  # ty: ignore[invalid-assignment]


class TemplateView(View):
    """
    Render a template.
    """

    template_name: str | None = None

    def get_template_context(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "template_names": self.get_template_names(),
            "DEBUG": settings.DEBUG,
        }

    def get_template_names(self) -> list[str]:
        """
        Return a list of template names to be used for the request.
        """
        if self.template_name:
            return [self.template_name]

        return []

    def get_template(self) -> Template:
        template_names = self.get_template_names()

        if isinstance(template_names, str):
            raise ImproperlyConfigured(
                f"{self.__class__.__name__}.get_template_names() must return a list of strings, "
                f"not a string. Did you mean to return ['{template_names}']?"
            )

        if not template_names:
            raise ImproperlyConfigured(
                f"{self.__class__.__name__} requires a template_name or get_template_names()."
            )

        for template_name in template_names:
            try:
                return Template(template_name)
            except TemplateFileMissing:
                pass

        raise TemplateFileMissing(template_names)

    def render_template(self) -> str:
        return self.get_template().render(self.get_template_context())

    def get(self) -> Response:
        return Response(self.render_template())

    def handle_exception(self, exc: Exception) -> Response:
        """Render `{status}.html` for the exception, falling through on missing template."""
        status = exc.status_code if isinstance(exc, HTTPException) else 500
        try:
            body = Template(f"{status}.html").render(
                {
                    "request": self.request,
                    "status_code": status,
                    "exception": exc,
                    "DEBUG": settings.DEBUG,
                }
            )
            return Response(body, status_code=status)
        except TemplateFileMissing:
            # Defer to the framework default for plain-text rendering.
            # `from None` keeps observability tools from seeing
            # `TemplateFileMissing` as the suppressed cause of `exc`.
            raise exc from None
        except Exception as render_exc:
            if settings.DEBUG:
                raise
            logger.error(
                "Error template render failed",
                extra={
                    "path": self.request.path,
                    "status_code": status,
                    "request": self.request,
                },
                exc_info=render_exc,
            )
            return Response(status_code=status)


class NotFoundView(TemplateView):
    """Catchall view: raises 404 before method dispatch, renders `404.html`."""

    def before_request(self) -> NoReturn:
        raise NotFoundError404


class FormView[F: "BaseForm"](TemplateView):
    """A view for displaying a form and rendering a template response.

    Generic over the form type. Subclasses that want type-safe access to
    their specific form should parameterize: `FormView[MyForm]`. The
    `form_class` attribute must still be set separately at runtime.
    """

    form_class: type[F] | None = None
    success_url: Callable | str | None = None

    def get_form(self) -> F:
        """Return an instance of the form to be used in this view."""
        if not self.form_class:
            raise ImproperlyConfigured(
                f"No form class provided. Define {self.__class__.__name__}.form_class or override "
                f"{self.__class__.__name__}.get_form()."
            )
        return self.form_class(**self.get_form_kwargs())

    def get_form_kwargs(self) -> dict[str, Any]:
        """Return the keyword arguments for instantiating the form."""
        return {
            "initial": {},
            "request": self.request,
        }

    def get_success_url(self, form: F) -> str:
        """Return the URL to redirect to after processing a valid form."""
        if not self.success_url:
            raise ImproperlyConfigured("No URL to redirect to. Provide a success_url.")
        return str(self.success_url)  # success_url may be lazy

    def form_valid(self, form: F) -> Response:
        """If the form is valid, redirect to the supplied URL."""
        return RedirectResponse(self.get_success_url(form))

    def form_invalid(self, form: F) -> Response:
        """If the form is invalid, render the invalid form."""
        context = {
            **self.get_template_context(),
            "form": form,
        }
        return Response(self.get_template().render(context))

    def get_template_context(self) -> dict[str, Any]:
        """Insert the form into the context dict."""
        context = super().get_template_context()
        context["form"] = self.get_form()
        return context

    def post(self) -> Response:
        """
        Handle POST requests: instantiate a form instance with the passed
        POST variables and then check if it's valid.
        """
        form = self.get_form()
        if form.is_valid():
            return self.form_valid(form)
        else:
            return self.form_invalid(form)


class CreateView(FormView):
    """
    View for creating a new object, with a response rendered by a template.
    """

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

    def form_valid(self, form: BaseForm) -> Response:
        """If the form is valid, save the associated model."""
        self.object = form.save()  # ty: ignore[unresolved-attribute]
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

    def form_valid(self, form: BaseForm) -> Response:
        """If the form is valid, save the associated model."""
        form.save()  # ty: ignore[unresolved-attribute]
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

    def form_valid(self, form: BaseForm) -> Response:
        """If the form is valid, save the associated model."""
        form.save()  # ty: ignore[unresolved-attribute]
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


__all__ = [
    "TemplateView",
    "NotFoundView",
    "FormView",
    "CreateView",
    "UpdateView",
    "DeleteView",
    "DetailView",
    "ListView",
]
