# bolt-auth

Create users and authenticate them.

## Installation

- install bolt-auth
- install bolt-sessions
- optionally bolt-passwords, etc.
- add bolt.auth to installed packages

```python
INSTALLED_PACKAGES = [
    # ...
    "bolt.auth",
]
```

```
# settings.py
MIDDLEWARE = [
    "bolt.middleware.security.SecurityMiddleware",
    "bolt.assets.whitenoise.middleware.WhiteNoiseMiddleware",
    "bolt.sessions.middleware.SessionMiddleware",  # <-- Add SessionMiddleware
    "bolt.middleware.common.CommonMiddleware",
    "bolt.csrf.middleware.CsrfViewMiddleware",
    "bolt.auth.middleware.AuthenticationMiddleware",  # <-- Add AuthenticationMiddleware
    "bolt.middleware.clickjacking.XFrameOptionsMiddleware",
]
```
