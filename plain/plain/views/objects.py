from plain.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from plain.forms import Form
from plain.http import Http404, Response

from .forms import FormView
from .templates import TemplateView


class ObjectTemplateViewMixin:
    context_object_name = ""

    def get(self) -> Response:
        self.load_object()
        return self.render_template()

    def load_object(self) -> None:
        try:
            self.object = self.get_object()
        except ObjectDoesNotExist:
            raise Http404

        if not self.object:
            # Also raise 404 if the object is None
            raise Http404

    def get_object(self):  # Intentionally untyped... subclasses must override this.
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


class CreateView(ObjectTemplateViewMixin, FormView):
    """
    View for creating a new object, with a response rendered by a template.
    """

    def post(self) -> Response:
        """
        Handle POST requests: instantiate a form instance with the passed
        POST variables and then check if it's valid.
        """
        # Context expects self.object to exist
        self.load_object()
        return super().post()

    def load_object(self) -> None:
        self.object = None

    # TODO? would rather you have to specify this...
    def get_success_url(self, form):
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

    def form_valid(self, form):
        """If the form is valid, save the associated model."""
        self.object = form.save()
        return super().form_valid(form)


class UpdateView(ObjectTemplateViewMixin, FormView):
    """View for updating an object, with a response rendered by a template."""

    def post(self) -> Response:
        """
        Handle POST requests: instantiate a form instance with the passed
        POST variables and then check if it's valid.
        """
        self.load_object()
        return super().post()

    def get_success_url(self, form):
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

    def form_valid(self, form):
        """If the form is valid, save the associated model."""
        self.object = form.save()
        return super().form_valid(form)

    def get_form_kwargs(self):
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
        def __init__(self, instance, *args, **kwargs):
            self.instance = instance
            super().__init__(*args, **kwargs)

        def save(self):
            self.instance.delete()

    form_class = EmptyDeleteForm

    def post(self) -> Response:
        """
        Handle POST requests: instantiate a form instance with the passed
        POST variables and then check if it's valid.
        """
        self.load_object()
        return super().post()

    def get_form_kwargs(self):
        """Return the keyword arguments for instantiating the form."""
        kwargs = super().get_form_kwargs()
        kwargs.update({"instance": self.object})
        return kwargs

    def form_valid(self, form):
        """If the form is valid, save the associated model."""
        form.save()
        return super().form_valid(form)


class ListView(TemplateView):
    """
    Render some list of objects, set by `self.get_queryset()`, with a response
    rendered by a template.
    """

    context_object_name = ""

    def get(self) -> Response:
        self.objects = self.get_objects()
        return super().get()

    def get_objects(self):
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
