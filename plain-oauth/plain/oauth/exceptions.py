class OAuthError(Exception):
    """Base class for OAuth errors"""

    message = "An error occurred during the OAuth process."


class OAuthStateMissingError(OAuthError):
    message = "The state parameter is missing. Please try again."


class OAuthStateMismatchError(OAuthError):
    message = "The state parameter did not match. Please try again."


class OAuthUserAlreadyExistsError(OAuthError):
    message = "A user already exists with this email address. Please log in first and then connect this OAuth provider to the existing account."
