# Views

Class-based vs function-based views is a well-known debate in Django.

My take is that class-based views are the way to go,
but the implmentation of Django's base classes was too clunky.

I'm not saying it's easy to get "right",
but there's not much argument that it could be better.

Bolt includes my take on simpler class-based views:

- fewer base classes
- fewer method `*args` and `**kwargs`
- not explicitly tied to models
- can return a `Response` object, `str`, or `list`/`dict` (which will be converted to JSON)

http://django-vanilla-views.org/
