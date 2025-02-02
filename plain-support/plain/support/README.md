# plain-support

Provides support forms for your application.

## Usage

Include the support URLs in your `urls.py`:

```python
# app/urls.py
from plain.urls import include, path
import plain.support.urls

urlpatterns = [
    path("support/", include(plain.support.urls)),
    # ...
]
```

## Security considerations

Most support forms allow you to type in an email address. Be careful, because anybody can pretend to be anybody else at this point. Conversations either need to continue over email (which confirms they have access to the email account), or include a verification step (emailing a code to the email address, for example).
