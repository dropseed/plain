"""
WSGI config for <project> project.

It exposes the WSGI callable as a module-level variable named ``application``.
"""

from plain.internal.legacy.wsgi import get_wsgi_application

application = get_wsgi_application()
