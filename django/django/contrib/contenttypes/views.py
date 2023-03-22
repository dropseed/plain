from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, HttpResponseRedirect
from django.utils.translation import gettext as _


def shortcut(request, content_type_id, object_id):
    """
    Redirect to an object's page based on a content-type ID and an object ID.
    """
    # Look up the object, making sure it's got a get_absolute_url() function.
    try:
        content_type = ContentType.objects.get(pk=content_type_id)
        if not content_type.model_class():
            raise Http404(
                _("Content type %(ct_id)s object has no associated model")
                % {"ct_id": content_type_id}
            )
        obj = content_type.get_object_for_this_type(pk=object_id)
    except (ObjectDoesNotExist, ValueError):
        raise Http404(
            _("Content type %(ct_id)s object %(obj_id)s doesn’t exist")
            % {"ct_id": content_type_id, "obj_id": object_id}
        )

    try:
        get_absolute_url = obj.get_absolute_url
    except AttributeError:
        raise Http404(
            _("%(ct_name)s objects don’t have a get_absolute_url() method")
            % {"ct_name": content_type.name}
        )
    absurl = get_absolute_url()

    # Try to figure out the object's domain, so we can do a cross-site redirect
    # if necessary.

    # If the object actually defines a domain, we're done.
    if absurl.startswith(("http://", "https://", "//")):
        return HttpResponseRedirect(absurl)

    return HttpResponseRedirect(absurl)
