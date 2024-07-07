from plain.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from plain.http import Http404, Response, ResponseRedirect

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
        context["object"] = self.object
        if self.context_object_name:
            context[self.context_object_name] = self.object
        elif hasattr(self.object, "_meta"):
            context[self.object._meta.model_name] = self.object
        return context

    def get_template_names(self) -> list[str]:
        """
        Return a list of template names to be used for the request. May not be
        called if render_to_response() is overridden. Return the following list:

        * the value of ``template_name`` on the view (if provided)
          object instance that the view is operating upon (if available)
        * ``<package_label>/<model_name><template_name_suffix>.html``
        """
        if self.template_name:  # type: ignore
            return [self.template_name]  # type: ignore

        # If template_name isn't specified, it's not a problem --
        # we just start with an empty list.
        names = []

        # The least-specific option is the default <app>/<model>_detail.html;
        # only use this if the object in question is a model.
        if hasattr(self.object, "_meta"):
            object_meta = self.object._meta
            names.append(
                f"{object_meta.package_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            )

        return names


class DetailView(ObjectTemplateViewMixin, TemplateView):
    """
    Render a "detail" view of an object.

    By default this is a model instance looked up from `self.queryset`, but the
    view will support display of *any* object by overriding `self.get_object()`.
    """

    template_name_suffix = "_detail"


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
    def get_success_url(self):
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

    template_name_suffix = "_form"

    def post(self) -> Response:
        """
        Handle POST requests: instantiate a form instance with the passed
        POST variables and then check if it's valid.
        """
        self.load_object()
        return super().post()

    def get_success_url(self):
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


class DeleteView(ObjectTemplateViewMixin, TemplateView):
    """
    View for deleting an object retrieved with self.get_object(), with a
    response rendered by a template.
    """

    template_name_suffix = "_confirm_delete"

    def get_form_kwargs(self):
        """Return the keyword arguments for instantiating the form."""
        kwargs = super().get_form_kwargs()
        kwargs.update({"instance": self.object})
        return kwargs

    def get_success_url(self):
        if self.success_url:
            return self.success_url.format(**self.object.__dict__)
        else:
            raise ImproperlyConfigured("No URL to redirect to. Provide a success_url.")

    def post(self):
        self.load_object()
        self.object.delete()
        return ResponseRedirect(self.get_success_url())


class ListView(TemplateView):
    """
    Render some list of objects, set by `self.get_queryset()`, with a response
    rendered by a template.
    """

    template_name_suffix = "_list"
    context_object_name = "objects"

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
        context[self.context_object_name] = self.objects
        return context

    def get_template_names(self) -> list[str]:
        """
        Return a list of template names to be used for the request. May not be
        called if render_to_response() is overridden. Return the following list:

        * the value of ``template_name`` on the view (if provided)
          object instance that the view is operating upon (if available)
        * ``<package_label>/<model_name><template_name_suffix>.html``
        """
        if self.template_name:  # type: ignore
            return [self.template_name]  # type: ignore

        # If template_name isn't specified, it's not a problem --
        # we just start with an empty list.
        names = []

        # The least-specific option is the default <app>/<model>_detail.html;
        # only use this if the object in question is a model.
        if hasattr(self.objects, "model") and hasattr(self.objects.model, "_meta"):
            object_meta = self.objects.model._meta
            names.append(
                f"{object_meta.package_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            )

        return names
