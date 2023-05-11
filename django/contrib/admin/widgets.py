"""
Form Widget classes specific to the Django admin site.
"""
import copy
import json

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db.models import CASCADE, UUIDField
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch
from django.utils.html import smart_urlquote
from django.utils.http import urlencode
from django.utils.text import Truncator
from django.utils.translation import get_language
from django.utils.translation import gettext as _


class FilteredSelectMultiple(forms.SelectMultiple):
    """
    A SelectMultiple with a JavaScript filter interface.

    Note that the resulting JavaScript assumes that the jsi18n
    catalog has been loaded in the page
    """

    class Media:
        js = [
            "admin/js/core.js",
            "admin/js/SelectBox.js",
            "admin/js/SelectFilter2.js",
        ]

    def __init__(self, verbose_name, is_stacked, attrs=None, choices=()):
        self.verbose_name = verbose_name
        self.is_stacked = is_stacked
        super().__init__(attrs, choices)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["attrs"]["class"] = "selectfilter"
        if self.is_stacked:
            context["widget"]["attrs"]["class"] += "stacked"
        context["widget"]["attrs"]["data-field-name"] = self.verbose_name
        context["widget"]["attrs"]["data-is-stacked"] = int(self.is_stacked)
        return context


class AdminDateWidget(forms.DateInput):
    class Media:
        js = [
            "admin/js/calendar.js",
            "admin/js/admin/DateTimeShortcuts.js",
        ]

    def __init__(self, attrs=None, format=None):
        attrs = {"class": "vDateField", "size": "10", **(attrs or {})}
        super().__init__(attrs=attrs, format=format)


class AdminTimeWidget(forms.TimeInput):
    class Media:
        js = [
            "admin/js/calendar.js",
            "admin/js/admin/DateTimeShortcuts.js",
        ]

    def __init__(self, attrs=None, format=None):
        attrs = {"class": "vTimeField", "size": "8", **(attrs or {})}
        super().__init__(attrs=attrs, format=format)


class AdminSplitDateTime(forms.SplitDateTimeWidget):
    """
    A SplitDateTime Widget that has some admin-specific styling.
    """

    template_name = "admin/widgets/split_datetime.html"

    def __init__(self, attrs=None):
        widgets = [AdminDateWidget, AdminTimeWidget]
        # Note that we're calling MultiWidget, not SplitDateTimeWidget, because
        # we want to define widgets.
        forms.MultiWidget.__init__(self, widgets, attrs)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["date_label"] = _("Date:")
        context["time_label"] = _("Time:")
        return context


class AdminRadioSelect(forms.RadioSelect):
    template_name = "admin/widgets/radio.html"


class AdminFileWidget(forms.ClearableFileInput):
    template_name = "admin/widgets/clearable_file_input.html"


def url_params_from_lookup_dict(lookups):
    """
    Convert the type of lookups specified in a ForeignKey limit_choices_to
    attribute to a dictionary of query parameters
    """
    params = {}
    if lookups and hasattr(lookups, "items"):
        for k, v in lookups.items():
            if callable(v):
                v = v()
            if isinstance(v, (tuple, list)):
                v = ",".join(str(x) for x in v)
            elif isinstance(v, bool):
                v = ("0", "1")[v]
            else:
                v = str(v)
            params[k] = v
    return params


class ForeignKeyRawIdWidget(forms.TextInput):
    """
    A Widget for displaying ForeignKeys in the "raw_id" interface rather than
    in a <select> box.
    """

    template_name = "admin/widgets/foreign_key_raw_id.html"

    def __init__(self, rel, admin_site, attrs=None, using=None):
        self.rel = rel
        self.admin_site = admin_site
        self.db = using
        super().__init__(attrs)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        rel_to = self.rel.model
        if rel_to in self.admin_site._registry:
            # The related object is registered with the same AdminSite
            related_url = reverse(
                "admin:%s_%s_changelist"
                % (
                    rel_to._meta.app_label,
                    rel_to._meta.model_name,
                ),
                current_app=self.admin_site.name,
            )

            params = self.url_parameters()
            if params:
                related_url += "?" + urlencode(params)
            context["related_url"] = related_url
            context["link_title"] = _("Lookup")
            # The JavaScript code looks for this class.
            css_class = "vForeignKeyRawIdAdminField"
            if isinstance(self.rel.get_related_field(), UUIDField):
                css_class += " vUUIDField"
            context["widget"]["attrs"].setdefault("class", css_class)
        else:
            context["related_url"] = None
        if context["widget"]["value"]:
            context["link_label"], context["link_url"] = self.label_and_url_for_value(
                value
            )
        else:
            context["link_label"] = None
        return context

    def base_url_parameters(self):
        limit_choices_to = self.rel.limit_choices_to
        if callable(limit_choices_to):
            limit_choices_to = limit_choices_to()
        return url_params_from_lookup_dict(limit_choices_to)

    def url_parameters(self):
        from django.contrib.admin.views.main import TO_FIELD_VAR

        params = self.base_url_parameters()
        params.update({TO_FIELD_VAR: self.rel.get_related_field().name})
        return params

    def label_and_url_for_value(self, value):
        key = self.rel.get_related_field().name
        try:
            obj = self.rel.model._default_manager.using(self.db).get(**{key: value})
        except (ValueError, self.rel.model.DoesNotExist, ValidationError):
            return "", ""

        try:
            url = reverse(
                "%s:%s_%s_change"
                % (
                    self.admin_site.name,
                    obj._meta.app_label,
                    obj._meta.object_name.lower(),
                ),
                args=(obj.pk,),
            )
        except NoReverseMatch:
            url = ""  # Admin not registered for target model.

        return Truncator(obj).words(14), url


class ManyToManyRawIdWidget(ForeignKeyRawIdWidget):
    """
    A Widget for displaying ManyToMany ids in the "raw_id" interface rather than
    in a <select multiple> box.
    """

    template_name = "admin/widgets/many_to_many_raw_id.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        if self.rel.model in self.admin_site._registry:
            # The related object is registered with the same AdminSite
            context["widget"]["attrs"]["class"] = "vManyToManyRawIdAdminField"
        return context

    def url_parameters(self):
        return self.base_url_parameters()

    def label_and_url_for_value(self, value):
        return "", ""

    def value_from_datadict(self, data, files, name):
        value = data.get(name)
        if value:
            return value.split(",")

    def format_value(self, value):
        return ",".join(str(v) for v in value) if value else ""


class RelatedFieldWidgetWrapper(forms.Widget):
    """
    This class is a wrapper to a given widget to add the add icon for the
    admin interface.
    """

    template_name = "admin/widgets/related_widget_wrapper.html"

    def __init__(
        self,
        widget,
        rel,
        admin_site,
        can_add_related=None,
        can_change_related=False,
        can_delete_related=False,
        can_view_related=False,
    ):
        self.needs_multipart_form = widget.needs_multipart_form
        self.attrs = widget.attrs
        self.choices = widget.choices
        self.widget = widget
        self.rel = rel
        # Backwards compatible check for whether a user can add related
        # objects.
        if can_add_related is None:
            can_add_related = rel.model in admin_site._registry
        self.can_add_related = can_add_related
        # XXX: The UX does not support multiple selected values.
        multiple = getattr(widget, "allow_multiple_selected", False)
        self.can_change_related = not multiple and can_change_related
        # XXX: The deletion UX can be confusing when dealing with cascading deletion.
        cascade = getattr(rel, "on_delete", None) is CASCADE
        self.can_delete_related = not multiple and not cascade and can_delete_related
        self.can_view_related = not multiple and can_view_related
        # so we can check if the related object is registered with this AdminSite
        self.admin_site = admin_site

    def __deepcopy__(self, memo):
        obj = copy.copy(self)
        obj.widget = copy.deepcopy(self.widget, memo)
        obj.attrs = self.widget.attrs
        memo[id(self)] = obj
        return obj

    @property
    def is_hidden(self):
        return self.widget.is_hidden

    @property
    def media(self):
        return self.widget.media

    def get_related_url(self, info, action, *args):
        return reverse(
            "admin:%s_%s_%s" % (info + (action,)),
            current_app=self.admin_site.name,
            args=args,
        )

    def get_context(self, name, value, attrs):
        from django.contrib.admin.views.main import IS_POPUP_VAR, TO_FIELD_VAR

        rel_opts = self.rel.model._meta
        info = (rel_opts.app_label, rel_opts.model_name)
        self.widget.choices = self.choices
        related_field_name = self.rel.get_related_field().name
        url_params = "&".join(
            "%s=%s" % param
            for param in [
                (TO_FIELD_VAR, related_field_name),
                (IS_POPUP_VAR, 1),
            ]
        )
        context = {
            "rendered_widget": self.widget.render(name, value, attrs),
            "is_hidden": self.is_hidden,
            "name": name,
            "url_params": url_params,
            "model": rel_opts.verbose_name,
            "can_add_related": self.can_add_related,
            "can_change_related": self.can_change_related,
            "can_delete_related": self.can_delete_related,
            "can_view_related": self.can_view_related,
            "model_has_limit_choices_to": self.rel.limit_choices_to,
        }
        if self.can_add_related:
            context["add_related_url"] = self.get_related_url(info, "add")
        if self.can_delete_related:
            context["delete_related_template_url"] = self.get_related_url(
                info, "delete", "__fk__"
            )
        if self.can_view_related or self.can_change_related:
            context["view_related_url_params"] = f"{TO_FIELD_VAR}={related_field_name}"
            context["change_related_template_url"] = self.get_related_url(
                info, "change", "__fk__"
            )
        return context

    def value_from_datadict(self, data, files, name):
        return self.widget.value_from_datadict(data, files, name)

    def value_omitted_from_data(self, data, files, name):
        return self.widget.value_omitted_from_data(data, files, name)

    def id_for_label(self, id_):
        return self.widget.id_for_label(id_)


class AdminTextareaWidget(forms.Textarea):
    def __init__(self, attrs=None):
        super().__init__(attrs={"class": "vLargeTextField", **(attrs or {})})


class AdminTextInputWidget(forms.TextInput):
    def __init__(self, attrs=None):
        super().__init__(attrs={"class": "vTextField", **(attrs or {})})


class AdminEmailInputWidget(forms.EmailInput):
    def __init__(self, attrs=None):
        super().__init__(attrs={"class": "vTextField", **(attrs or {})})


class AdminURLFieldWidget(forms.URLInput):
    template_name = "admin/widgets/url.html"

    def __init__(self, attrs=None, validator_class=URLValidator):
        super().__init__(attrs={"class": "vURLField", **(attrs or {})})
        self.validator = validator_class()

    def get_context(self, name, value, attrs):
        try:
            self.validator(value if value else "")
            url_valid = True
        except ValidationError:
            url_valid = False
        context = super().get_context(name, value, attrs)
        context["current_label"] = _("Currently:")
        context["change_label"] = _("Change:")
        context["widget"]["href"] = (
            smart_urlquote(context["widget"]["value"]) if value else ""
        )
        context["url_valid"] = url_valid
        return context


class AdminIntegerFieldWidget(forms.NumberInput):
    class_name = "vIntegerField"

    def __init__(self, attrs=None):
        super().__init__(attrs={"class": self.class_name, **(attrs or {})})


class AdminBigIntegerFieldWidget(AdminIntegerFieldWidget):
    class_name = "vBigIntegerField"


class AdminUUIDInputWidget(forms.TextInput):
    def __init__(self, attrs=None):
        super().__init__(attrs={"class": "vUUIDField", **(attrs or {})})
