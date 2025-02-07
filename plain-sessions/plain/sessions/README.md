## Sessions - db backed

Manage sessions and save them in the database.

- associate with users?
- devices?

## Usage

To use sessions in your views, access the `request.session` object:

```python
# Example view using sessions
class MyView(View):
    def get(self):
        # Store a value in the session
        self.request.session['key'] = 'value'
        # Retrieve a value from the session
        value = self.request.session.get('key')
```
