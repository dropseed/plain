from forgequerystats.core import tidy_stack


def test_tidy_stack():
    # Some has already been removed from this, but trying to get the rest
    stack = """  File "/app/.heroku/python/bin/gunicorn", line 8, in <module>
    sys.exit(run())
  File "/app/.heroku/python/lib/python3.9/site-packages/gunicorn/app/wsgiapp.py", line 67, in run
    WSGIApplication("%(prog)s [OPTIONS] [APP_MODULE]").run()
  File "/app/.heroku/python/lib/python3.9/site-packages/gunicorn/app/base.py", line 231, in run
    super().run()
  File "/app/.heroku/python/lib/python3.9/site-packages/gunicorn/app/base.py", line 72, in run
    Arbiter(self).run()
  File "/app/.heroku/python/lib/python3.9/site-packages/gunicorn/arbiter.py", line 202, in run
    self.manage_workers()
  File "/app/.heroku/python/lib/python3.9/site-packages/gunicorn/arbiter.py", line 551, in manage_workers
    self.spawn_workers()
  File "/app/.heroku/python/lib/python3.9/site-packages/gunicorn/arbiter.py", line 622, in spawn_workers
    self.spawn_worker()
  File "/app/.heroku/python/lib/python3.9/site-packages/gunicorn/arbiter.py", line 589, in spawn_worker
    worker.init_process()
  File "/app/.heroku/python/lib/python3.9/site-packages/gunicorn/workers/base.py", line 142, in init_process
    self.run()
  File "/app/.heroku/python/lib/python3.9/site-packages/gunicorn/workers/sync.py", line 125, in run
    self.run_for_one(timeout)
  File "/app/.heroku/python/lib/python3.9/site-packages/gunicorn/workers/sync.py", line 69, in run_for_one
    self.accept(listener)
  File "/app/.heroku/python/lib/python3.9/site-packages/gunicorn/workers/sync.py", line 31, in accept
    self.handle(listener, client, addr)
  File "/app/.heroku/python/lib/python3.9/site-packages/gunicorn/workers/sync.py", line 136, in handle
    self.handle_request(listener, req, client, addr)
  File "/app/.heroku/python/lib/python3.9/site-packages/gunicorn/workers/sync.py", line 179, in handle_request
    respiter = self.wsgi(environ, resp.start_response)
  File "/app/.heroku/python/lib/python3.9/site-packages/sentry_sdk/integrations/django/__init__.py", line 127, in sentry_patched_wsgi_handler
    return SentryWsgiMiddleware(bound_old_app, use_x_forwarded_for)(
  File "/app/.heroku/python/lib/python3.9/site-packages/sentry_sdk/integrations/wsgi.py", line 132, in __call__
    rv = self.app(
  File "/app/.heroku/python/lib/python3.9/site-packages/sentry_sdk/integrations/django/middleware.py", line 175, in __call__
    return f(*args, **kwargs)
  File "/app/.heroku/python/lib/python3.9/site-packages/sentry_sdk/integrations/django/middleware.py", line 175, in __call__
    return f(*args, **kwargs)
  File "/app/.heroku/python/lib/python3.9/site-packages/whitenoise/middleware.py", line 60, in __call__
    response = self.get_response(request)
  File "/app/.heroku/python/lib/python3.9/site-packages/sentry_sdk/integrations/django/middleware.py", line 175, in __call__
    return f(*args, **kwargs)
  File "/app/.heroku/python/lib/python3.9/site-packages/sentry_sdk/integrations/django/middleware.py", line 175, in __call__
    return f(*args, **kwargs)
  File "/app/.heroku/python/lib/python3.9/site-packages/sentry_sdk/integrations/django/middleware.py", line 175, in __call__
    return f(*args, **kwargs)
  File "/app/.heroku/python/lib/python3.9/site-packages/sentry_sdk/integrations/django/middleware.py", line 175, in __call__
    return f(*args, **kwargs)
  File "/app/.heroku/python/lib/python3.9/site-packages/sentry_sdk/integrations/django/middleware.py", line 175, in __call__
    return f(*args, **kwargs)
  File "/app/.heroku/python/lib/python3.9/site-packages/sentry_sdk/integrations/django/middleware.py", line 175, in __call__
    return f(*args, **kwargs)
  File "/app/.heroku/python/lib/python3.9/site-packages/forgepro/stafftoolbar/querystats/middleware.py", line 34, in __call__
    is_staff = self.is_staff_request(request)
  File "/app/.heroku/python/lib/python3.9/site-packages/forgepro/stafftoolbar/querystats/middleware.py", line 72, in is_staff_request
    and request.user.is_authenticated
  File "/app/.heroku/python/lib/python3.9/site-packages/django/contrib/auth/middleware.py", line 25, in <lambda>
    request.user = SimpleLazyObject(lambda: get_user(request))
  File "/app/.heroku/python/lib/python3.9/site-packages/django/contrib/auth/middleware.py", line 11, in get_user
    request._cached_user = auth.get_user(request)
  File "/app/.heroku/python/lib/python3.9/site-packages/django/contrib/auth/__init__.py", line 191, in get_user
    user_id = _get_user_session_key(request)
  File "/app/.heroku/python/lib/python3.9/site-packages/django/contrib/auth/__init__.py", line 60, in _get_user_session_key
    return get_user_model()._meta.pk.to_python(request.session[SESSION_KEY])
  File "/app/.heroku/python/lib/python3.9/site-packages/django/contrib/sessions/backends/base.py", line 53, in __getitem__
    return self._session[key]
  File "/app/.heroku/python/lib/python3.9/site-packages/django/contrib/sessions/backends/base.py", line 192, in _get_session
    self._session_cache = self.load()
  File "/app/.heroku/python/lib/python3.9/site-packages/django/contrib/sessions/backends/db.py", line 42, in load
    s = self._get_session_from_db()
  File "/app/.heroku/python/lib/python3.9/site-packages/django/contrib/sessions/backends/db.py", line 32, in _get_session_from_db
    return self.model.objects.get(
  File "/app/.heroku/python/lib/python3.9/site-packages/sentry_sdk/integrations/django/__init__.py", line 544, in execute
    return real_execute(self, sql, params)"""

    # The actual traceback.format_stack() includes newlines when iterating,
    # so joining here is not exactly the same as get_stack
    assert (
        "\n".join(tidy_stack(stack.splitlines()))
        == """  File "/app/.heroku/python/lib/python3.9/site-packages/forgepro/stafftoolbar/querystats/middleware.py", line 34, in __call__
    is_staff = self.is_staff_request(request)
  File "/app/.heroku/python/lib/python3.9/site-packages/forgepro/stafftoolbar/querystats/middleware.py", line 72, in is_staff_request
    and request.user.is_authenticated
  File "/app/.heroku/python/lib/python3.9/site-packages/django/contrib/auth/middleware.py", line 25, in <lambda>
    request.user = SimpleLazyObject(lambda: get_user(request))
  File "/app/.heroku/python/lib/python3.9/site-packages/django/contrib/auth/middleware.py", line 11, in get_user
    request._cached_user = auth.get_user(request)
  File "/app/.heroku/python/lib/python3.9/site-packages/django/contrib/auth/__init__.py", line 191, in get_user
    user_id = _get_user_session_key(request)
  File "/app/.heroku/python/lib/python3.9/site-packages/django/contrib/auth/__init__.py", line 60, in _get_user_session_key
    return get_user_model()._meta.pk.to_python(request.session[SESSION_KEY])
  File "/app/.heroku/python/lib/python3.9/site-packages/django/contrib/sessions/backends/base.py", line 53, in __getitem__
    return self._session[key]
  File "/app/.heroku/python/lib/python3.9/site-packages/django/contrib/sessions/backends/base.py", line 192, in _get_session
    self._session_cache = self.load()
  File "/app/.heroku/python/lib/python3.9/site-packages/django/contrib/sessions/backends/db.py", line 42, in load
    s = self._get_session_from_db()
  File "/app/.heroku/python/lib/python3.9/site-packages/django/contrib/sessions/backends/db.py", line 32, in _get_session_from_db
    return self.model.objects.get("""
    )
