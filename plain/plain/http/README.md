# HTTP

**HTTP request and response handling.**

- [Overview](#overview)

## Overview

Typically you will interact with [Request](request.py#Request) and [Response](response.py#ResponseBase) objects in your views and middleware.

```python
from plain.views import View
from plain.http import Response

class ExampleView(View):
    def get(self):
        # Accessing a request header
        print(self.request.headers.get("Example-Header"))

        # Accessing a query parameter
        print(self.request.query_params.get("example"))

        # Creating a response
        response = Response("Hello, world!", status_code=200)

        # Setting a response header
        response.headers["Example-Header"] = "Example Value"

        return response
```
