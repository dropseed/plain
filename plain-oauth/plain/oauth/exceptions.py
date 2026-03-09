__all__ = [
    "OAuthError",
    "OAuthStateMismatchError",
    "OAuthStateMissingError",
    "OAuthUserAlreadyExistsError",
]


class OAuthError(Exception):
    """Base class for OAuth errors"""

    message = "An error occurred during the OAuth process."
    template_name = ""

    def __init__(self, message="", *, provider_key=""):
        self.provider_key = provider_key
        if message:
            self.message = message
        super().__init__(self.message)


class OAuthStateMissingError(OAuthError):
    message = "The OAuth state is missing. Your session may have expired or cookies may be blocked. Please try again."
    template_name = "oauth/state_missing.html"


class OAuthStateMismatchError(OAuthError):
    message = "The state parameter did not match. Please try again."
    template_name = "oauth/state_mismatch.html"


class OAuthUserAlreadyExistsError(OAuthError):
    message = "A user already exists with this email address. Please log in first and then connect this OAuth provider to the existing account."
    template_name = "oauth/user_already_exists.html"

    def __init__(self, *, provider_key="", user_model_fields=None):
        self.user_model_fields = user_model_fields or {}
        super().__init__(provider_key=provider_key)
