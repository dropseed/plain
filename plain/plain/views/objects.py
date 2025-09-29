from functools import cached_property
from typing import Any

from plain.exceptions import ImproperlyConfigured

try:
    from plain.models.exceptions import ObjectDoesNotExist
except ImportError:
    ObjectDoesNotExist = None  # type: ignore[assignment]

from plain.forms import Form
from plain.http import Http404

from .forms import FormView
from .templates import TemplateView


class CreateView(FormView):
    """
    View for creating a new object, with a response rendered by a template.
    """

    # TODO? would rather you have to specify this...
    def get_success_url(self, form: Form) -> str:
        """Return the URL to redirect to after processing a valid form."""
        if self.success_url:
            url = self.success_url.format(**self.object.__dict__)
        else:
            try:
                url = self.object.get_absolute_url()
            except AttributeError:
                raise ImproperlyConfigured(
                    "No URL to redirect to.  Either provide a url or define"
                    " a get_absolute_url method on the Model."
                )
        return url

    def form_valid(self, form: Form) -> Any:
        """If the form is valid, save the associated model."""
        self.object = form.save()  # type: ignore[attr-defined]
        return super().form_valid(form)


class ObjectTemplateViewMixin:
    context_object_name = ""

    @cached_property
    def object(self) -> Any:
        try:
            obj = self.get_object()
        except Exception as e:
            # If ObjectDoesNotExist is available and this is that exception, raise 404
            if ObjectDoesNotExist and isinstance(e, ObjectDoesNotExist):
                raise Http404
            # Otherwise, let other exceptions bubble up
            raise

        # Also raise 404 if get_object() returns None
        if not obj:
            raise Http404

        return obj

    def get_object(self) -> Any:
        raise NotImplementedError(
            f"get_object() is not implemented on {self.__class__.__name__}"
        )

    def get_template_context(self) -> dict:
        """Insert the single object into the context dict."""
        context = super().get_template_context()  # type: ignore
        context["object"] = (
            self.object
        )  # Some templates can benefit by always knowing a primary "object" can be present
        if self.context_object_name:
            context[self.context_object_name] = self.object
        return context


class DetailView(ObjectTemplateViewMixin, TemplateView):
    """
    Render a "detail" view of an object.

    By default this is a model instance looked up from `self.queryset`, but the
    view will support display of *any* object by overriding `self.get_object()`.
    """

    pass


class UpdateView(ObjectTemplateViewMixin, FormView):
    """View for updating an object, with a response rendered by a template."""

    def get_success_url(self, form: Form) -> str:
        """Return the URL to redirect to after processing a valid form."""
        if self.success_url:
            url = self.success_url.format(**self.object.__dict__)
        else:
            try:
                url = self.object.get_absolute_url()
            except AttributeError:
                raise ImproperlyConfigured(
                    "No URL to redirect to.  Either provide a url or define"
                    " a get_absolute_url method on the Model."
                )
        return url

    def form_valid(self, form: Form) -> Any:
        """If the form is valid, save the associated model."""
        form.save()  # type: ignore[attr-defined]
        return super().form_valid(form)

    def get_form_kwargs(self) -> dict:
        """Return the keyword arguments for instantiating the form."""
        kwargs = super().get_form_kwargs()
        kwargs.update({"instance": self.object})
        return kwargs


class DeleteView(ObjectTemplateViewMixin, FormView):
    """
    View for deleting an object retrieved with self.get_object(), with a
    response rendered by a template.
    """

    class EmptyDeleteForm(Form):
        def __init__(self, instance: Any, *args: object, **kwargs: object) -> None:
            self.instance = instance
            super().__init__(*args, **kwargs)

        def save(self) -> None:
            self.instance.delete()

    form_class = EmptyDeleteForm

    def get_form_kwargs(self) -> dict:
        """Return the keyword arguments for instantiating the form."""
        kwargs = super().get_form_kwargs()
        kwargs.update({"instance": self.object})
        return kwargs

    def form_valid(self, form: Form) -> Any:
        """If the form is valid, save the associated model."""
        form.save()  # type: ignore[attr-defined]
        return super().form_valid(form)


class ListView(TemplateView):
    """
    Render some list of objects, set by `self.get_queryset()`, with a response
    rendered by a template.
    """

    context_object_name = ""

    @cached_property
    def objects(self) -> Any:
        return self.get_objects()

    def get_objects(self) -> Any:
        raise NotImplementedError(
            f"get_objects() is not implemented on {self.__class__.__name__}"
        )

    def get_template_context(self) -> dict:
        """Insert the single object into the context dict."""
        context = super().get_template_context()  # type: ignore
        context["objects"] = self.objects
        if self.context_object_name:
            context[self.context_object_name] = self.objects
        return context
