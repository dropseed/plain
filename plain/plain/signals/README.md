# Signals

Run code when certain events happen.

```python
from plain.signals import request_finished


def on_request_finished(sender, **kwargs):
    print("Request finished!")


request_finished.connect(on_request_finished)
```
