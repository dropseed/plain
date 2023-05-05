"""
Views and functions for serving static files. These are only to be used during
development, and SHOULD NOT be used in a production setting.

"""
import os
import posixpath
import mimetypes
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotModified
from django.utils._os import safe_join
from django.utils.http import http_date, parse_http_date
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.bolt import jinja
from jinja2.exceptions import TemplateNotFound


def builtin_template_path(name):
    """
    Return a path to a builtin template.

    Avoid calling this function at the module level or in a class-definition
    because __file__ may not exist, e.g. in frozen environments.
    """
    return Path(__file__).parent / "templates" / name


def serve_static(request, path, document_root=None, show_indexes=False):
    """
    Serve static files below a given point in the directory structure.

    To use, put a URL pattern such as::

        from django.views.static import serve

        path('<path:path>', serve, {'document_root': '/path/to/my/files/'})

    in your URLconf. You must provide the ``document_root`` param. You may
    also set ``show_indexes`` to ``True`` if you'd like to serve a basic index
    of the directory.  This index view will use the template hardcoded below,
    but if you'd like to override it, you can create a template called
    ``static/directory_index.html``.
    """
    path = posixpath.normpath(path).lstrip("/")
    fullpath = Path(safe_join(document_root, path))
    if fullpath.is_dir():
        if show_indexes:
            return directory_index(path, fullpath)
        raise Http404(_("Directory indexes are not allowed here."))
    if not fullpath.exists():
        raise Http404(_("“%(path)s” does not exist") % {"path": fullpath})
    # Respect the If-Modified-Since header.
    statobj = fullpath.stat()
    if not was_modified_since(
        request.META.get("HTTP_IF_MODIFIED_SINCE"), statobj.st_mtime
    ):
        return HttpResponseNotModified()
    content_type, encoding = mimetypes.guess_type(str(fullpath))
    content_type = content_type or "application/octet-stream"
    response = FileResponse(fullpath.open("rb"), content_type=content_type)
    response.headers["Last-Modified"] = http_date(statobj.st_mtime)
    if encoding:
        response.headers["Content-Encoding"] = encoding
    return response


# Translatable string for static directory index template title.
template_translatable = gettext_lazy("Index of %(directory)s")


def directory_index(path, fullpath):
    try:
        t = jinja.environment.select_template(
            [
                "static/directory_index.html",
                "static/directory_index",
            ]
        )
    except TemplateNotFound:
        with builtin_template_path("directory_index.html").open(encoding="utf-8") as fh:
            t = jinja.environment.from_string(
                fh.read()
            )
        c = {}
    else:
        c = {}
    files = []
    for f in fullpath.iterdir():
        if not f.name.startswith("."):
            url = str(f.relative_to(fullpath))
            if f.is_dir():
                url += "/"
            files.append(url)
    c.update(
        {
            "directory": path + "/",
            "file_list": files,
        }
    )
    return HttpResponse(t.render(c))


def was_modified_since(header=None, mtime=0):
    """
    Was something modified since the user last downloaded it?

    header
      This is the value of the If-Modified-Since header.  If this is None,
      I'll just return True.

    mtime
      This is the modification time of the item we're talking about.
    """
    try:
        if header is None:
            raise ValueError
        header_mtime = parse_http_date(header)
        if int(mtime) > header_mtime:
            raise ValueError
    except (ValueError, OverflowError):
        return True
    return False




def serve(request, path, insecure=False, **kwargs):
    """
    Serve static files below a given point in the directory structure or
    from locations inferred from the staticfiles finders.

    To use, put a URL pattern such as::

        from django.contrib.staticfiles import views

        path('<path:path>', views.serve)

    in your URLconf.

    It uses the django.views.static.serve() view to serve the found files.
    """
    if not settings.DEBUG and not insecure:
        raise Http404
    normalized_path = posixpath.normpath(path).lstrip("/")
    absolute_path = finders.find(normalized_path)
    if not absolute_path:
        if path.endswith("/") or path == "":
            raise Http404("Directory indexes are not allowed here.")
        raise Http404("'%s' could not be found" % path)
    document_root, path = os.path.split(absolute_path)
    return serve_static(request, path, document_root=document_root, **kwargs)
