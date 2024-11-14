from pprint import pformat

from markupsafe import Markup, escape

from plain.http import Response
from plain.views.exceptions import ResponseException


def dd(*objs):
    """
    Dump and die.

    Dump the object and raise a ResponseException with the dump as the response content.
    """
    dump_strs = [
        Markup("<pre><code>") + escape(pformat(obj)) + Markup("</code></pre>")
        for obj in objs
    ]
    combined_dump_str = Markup("\n\n").join(dump_strs)

    print(f"Dumping objects:\n{combined_dump_str}")

    response = Response()
    response.status_code = 500
    response.content = combined_dump_str
    response.content_type = "text/html"
    raise ResponseException(response)
