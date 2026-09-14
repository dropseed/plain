"""Import paths for the email backends Plain ships.

Defined here so the settings value, the toolbar, the test fixture, and the
preflight checks all compare against the same strings.
"""

SMTP_BACKEND = "plain.email.backends.smtp.EmailBackend"
CONSOLE_BACKEND = "plain.email.backends.console.EmailBackend"
PREVIEW_BACKEND = "plain.email.backends.preview.EmailBackend"
LOCMEM_BACKEND = "plain.email.backends.locmem.EmailBackend"
