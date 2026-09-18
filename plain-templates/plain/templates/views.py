from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cached_property
from typing import Any, NoReturn

from plain.exceptions import ImproperlyConfigured
from plain.forms import Form, Invalid
from plain.http import NotFoundError404, Response, status_for_exception
from plain.logs import get_framework_logger
from plain.paginator import Page, Paginator
from plain.runtime import settings
from plain.views import View

from .core import Template, TemplateFileMissing

logger = get_framework_logger("plain.templates")

try:
    from plain.postgres.exceptions import ObjectDoesNotExist
except ImportError:
    ObjectDoesNotExist = None


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

    def render(self, *, status_code: int = 200, **context: Any) -> Response:
        """Render the template to a `Response`, layering `context` over `get_template_context()`.

        A handler passes what the template needs straight in —
        `self.render(form=form)` — rather than stashing it on `self` for
        `get_template_context()` to read back. Called with no arguments it
        renders `get_template_context()` as-is, which is what `get()` does.

        `status_code` sets the response status (a form's 422, say) —
        `Response.status_code` is fixed at construction, so this is the
        way to render a template at a non-200 status. The name is
        reserved: a template variable called `status_code` has to come
        from `get_template_context()` instead.
        """
        return Response(
            self.get_template().render({**self.get_template_context(), **context}),
            status_code=status_code,
        )

    def get(self) -> Response:
        return self.render()

    def render_form[F: Form](
        self,
        form_class: type[F],
        result: F | Invalid | None = None,
        *,
        values: dict[str, Any] | None = None,
        **context: Any,
    ) -> Response:
        """Render the template with `form_class` and a `form` result.

        The template receives `form_class` (for metadata: `form_class.email.required`)
        and `form` (a `Form | Invalid` for per-field value/errors via
        `field_value` / `field_errors`).

        `result` is whatever `validate()` returned (success or `Invalid`), or
        `None` for a blank render. `values` pre-fills a blank render with
        each field's `initial` applied first.

            self.render_form(NoteForm)                       # blank (GET)
            self.render_form(NoteForm, values=initial)       # pre-filled (edit GET)
            self.render_form(NoteForm, invalid_result)       # failed validate() (POST)

        For a custom failure (e.g. an authentication rejection that ran after
        `validate()` succeeded), construct an `Invalid` directly and pass it
        as `result`: `render_form(LoginForm, Invalid(errors=[...], raw=data))`.
        """
        if result is None:
            data: dict[str, Any] = {
                name: field.initial
                for name, field in form_class.fields().items()
                if field.initial is not None
            }
            if values:
                data.update(values)
            result = form_class(**data)
        return self.render(form_class=form_class, form=result, **context)

    def validate_form[F: Form](self, form_class: type[F]) -> F | Response:
        """Validate the request against `form_class`. Returns the typed form
        instance on success, or a re-rendered template `Response` (with the
        submission and its errors) on failure.

            result = self.validate_form(NoteForm)
            if isinstance(result, Response):
                return result
            # result is the typed NoteForm — every field cleaned

        Reads `request.form_data` and `request.files`, so it covers the
        ordinary HTML POST case without arguments. For other shapes (a JSON
        body, or a custom failure response) call `form_class.validate()`
        directly — this helper is the one-line case, not a wrapper.
        """
        result = form_class.validate(self.request.form_data, files=self.request.files)
        if not result:
            return self.render_form(form_class, result)
        return result

    def handle_exception(self, exc: Exception) -> Response:
        """Render `{status}.html` for the exception, falling through on missing template."""
        status = status_for_exception(exc)
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


class ListView(TemplateView, ABC):
    """
    Render some list of objects, set by `self.get_objects()`, with a response
    rendered by a template.

    Set `page_size` to paginate: the objects are wrapped in a `Paginator`, the
    page number is read from the `?page` query param (invalid values fall back
    to the first or last page), and the current `Page` is what lands in the
    template context — iterate it exactly like the full list. The page is also
    available as `page_obj` for rendering pagination controls; it is `None`
    when pagination is off. Override `get_page_size()` to compute the size per
    request.

    A paginated queryset needs a deterministic order (an `order_by()` or a
    model default) — unordered results can shift between pages. An empty
    `Page` is falsy, so check `page_obj is not none` to test whether
    pagination is on.
    """

    context_object_name = ""
    page_size: int | None = None

    @cached_property
    def objects(self) -> Any:
        return self.get_objects()

    @abstractmethod
    def get_objects(self) -> Any: ...

    def get_page_size(self) -> int | None:
        """Page size for pagination, or `None` to render the full list."""
        return self.page_size

    @cached_property
    def page_obj(self) -> Page | None:
        if (page_size := self.get_page_size()) is None:
            return None
        return Paginator(self.objects, page_size).get_page(
            self.request.query_params.get("page", 1)
        )

    def get_template_context(self) -> dict[str, Any]:
        """Insert the list of objects (or the current page of it) into the context dict."""
        context = super().get_template_context()
        page_obj = self.page_obj
        objects = page_obj if page_obj is not None else self.objects
        context["objects"] = objects
        context["page_obj"] = page_obj
        if self.context_object_name:
            context[self.context_object_name] = objects
        return context


__all__ = [
    "DetailView",
    "ListView",
    "NotFoundView",
    "TemplateView",
]
