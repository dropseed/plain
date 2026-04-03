"""OAuth 2.1 authorization server views.

Implements:
- Authorization server metadata (RFC 8414)
- Authorization endpoint (RFC 6749 §4.1.1, with PKCE per RFC 7636)
- Token endpoint (RFC 6749 §4.1.3, §6)
- Token revocation (RFC 7009)
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from plain.auth.views import AuthView
from plain.http import JsonResponse, RedirectResponse, Response, ResponseBase
from plain.runtime import settings
from plain.templates import Template
from plain.urls import reverse
from plain.utils import timezone
from plain.views.base import View

from .models import AccessToken, AuthorizationCode, OAuthApplication, RefreshToken


class AuthorizationServerMetadataView(View):
    """RFC 8414: OAuth 2.0 Authorization Server Metadata.

    Served at /.well-known/oauth-authorization-server
    """

    def get(self) -> JsonResponse:
        # Build the issuer URL from the request
        scheme = self.request.server_scheme
        host = self.request.host
        issuer = f"{scheme}://{host}"

        metadata = {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}{reverse('oauth_provider:authorize')}",
            "token_endpoint": f"{issuer}{reverse('oauth_provider:token')}",
            "revocation_endpoint": f"{issuer}{reverse('oauth_provider:revoke')}",
            "response_types_supported": ["code"],
            "grant_types_supported": [
                "authorization_code",
                "refresh_token",
            ],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_post",
            ],
            "revocation_endpoint_auth_methods_supported": [
                "client_secret_post",
            ],
        }

        if settings.OAUTH_PROVIDER_ALLOW_DYNAMIC_REGISTRATION:
            metadata["registration_endpoint"] = (
                f"{issuer}{reverse('oauth_provider:register')}"
            )

        return JsonResponse(metadata)


class AuthorizeView(AuthView):
    """OAuth 2.1 Authorization Endpoint.

    GET: Show consent form to the authenticated user.
    POST: Process the user's approve/deny decision.
    """

    login_required = True

    def _render(self, context: dict[str, Any]) -> Response:
        context["request"] = self.request
        html = Template("oauth_provider/authorize.html").render(context)
        return Response(html)

    def get(self) -> ResponseBase:
        context: dict[str, Any] = {}
        errors = self._validate_request()
        if errors:
            context["error"] = errors[0]
            return self._render(context)

        application = OAuthApplication.query.get(
            client_id=self.request.query_params.get("client_id")
        )
        context["application"] = application
        context["scope"] = self.request.query_params.get("scope", "")
        context["redirect_uri"] = self.request.query_params.get("redirect_uri", "")
        # Pass through all params for the POST form
        context["params"] = {
            "response_type": self.request.query_params.get("response_type"),
            "client_id": self.request.query_params.get("client_id"),
            "redirect_uri": self.request.query_params.get("redirect_uri", ""),
            "scope": self.request.query_params.get("scope", ""),
            "state": self.request.query_params.get("state", ""),
            "code_challenge": self.request.query_params.get("code_challenge", ""),
            "code_challenge_method": self.request.query_params.get(
                "code_challenge_method", ""
            ),
        }
        return self._render(context)

    def post(self) -> ResponseBase:
        errors = self._validate_request()
        if errors:
            return JsonResponse(
                {"error": "invalid_request", "error_description": errors[0]},
                status_code=400,
            )

        redirect_uri = self.request.form_data.get("redirect_uri", "")
        state = self.request.form_data.get("state", "")

        # User denied
        if self.request.form_data.get("action") != "approve":
            return _redirect_with_error(redirect_uri, "access_denied", state)

        client_id = self.request.form_data.get("client_id", "")
        scope = self.request.form_data.get("scope", "")
        code_challenge = self.request.form_data.get("code_challenge", "")
        code_challenge_method = self.request.form_data.get(
            "code_challenge_method", "S256"
        )

        try:
            application = OAuthApplication.query.get(client_id=client_id)
        except OAuthApplication.DoesNotExist:
            return JsonResponse(
                {"error": "invalid_client", "error_description": "Unknown client"},
                status_code=400,
            )

        if not application.is_valid_redirect_uri(redirect_uri):
            return JsonResponse(
                {
                    "error": "invalid_request",
                    "error_description": "Invalid redirect URI",
                },
                status_code=400,
            )

        # Create authorization code
        expires_at = timezone.now() + timedelta(
            seconds=settings.OAUTH_PROVIDER_CODE_EXPIRY
        )
        auth_code = AuthorizationCode(
            application=application,
            user=self.user,
            redirect_uri=redirect_uri,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            expires_at=expires_at,
        )
        auth_code.save()

        # Redirect back to client with the code
        separator = "&" if "?" in redirect_uri else "?"
        url = f"{redirect_uri}{separator}code={auth_code.code}"
        if state:
            url += f"&state={state}"

        return RedirectResponse(url, allow_external=True)

    def _validate_request(self) -> list[str]:
        """Validate the authorization request parameters. Returns list of errors."""
        errors: list[str] = []
        params = (
            self.request.query_params
            if self.request.method == "GET"
            else self.request.form_data
        )

        response_type = params.get("response_type", "")
        if response_type != "code":
            errors.append(
                f"Unsupported response_type: {response_type!r}. Must be 'code'."
            )

        client_id = params.get("client_id", "")
        if not client_id:
            errors.append("Missing client_id")
        else:
            try:
                OAuthApplication.query.get(client_id=client_id)
            except OAuthApplication.DoesNotExist:
                errors.append(f"Unknown client_id: {client_id}")

        code_challenge = params.get("code_challenge", "")
        code_challenge_method = params.get("code_challenge_method", "")
        if not code_challenge:
            errors.append("Missing code_challenge (PKCE is required)")
        if code_challenge_method and code_challenge_method != "S256":
            errors.append(
                f"Unsupported code_challenge_method: {code_challenge_method!r}. Must be 'S256'."
            )

        return errors


class TokenView(View):
    """OAuth 2.1 Token Endpoint.

    Handles:
    - authorization_code grant (with PKCE verification)
    - refresh_token grant
    """

    def post(self) -> JsonResponse:
        # Token endpoint uses form-encoded POST per RFC 6749 §4.1.3
        grant_type = self.request.form_data.get("grant_type", "")

        match grant_type:
            case "authorization_code":
                return self._handle_authorization_code()
            case "refresh_token":
                return self._handle_refresh_token()
            case _:
                return JsonResponse(
                    {
                        "error": "unsupported_grant_type",
                        "error_description": f"Unsupported grant_type: {grant_type!r}",
                    },
                    status_code=400,
                )

    def _authenticate_client(self) -> OAuthApplication | JsonResponse:
        """Authenticate the client via client_secret_post."""
        client_id = self.request.form_data.get("client_id", "")
        client_secret = self.request.form_data.get("client_secret", "")

        if not client_id or not client_secret:
            return JsonResponse(
                {
                    "error": "invalid_client",
                    "error_description": "Missing client_id or client_secret",
                },
                status_code=401,
            )

        try:
            application = OAuthApplication.query.get(client_id=client_id)
        except OAuthApplication.DoesNotExist:
            return JsonResponse(
                {"error": "invalid_client", "error_description": "Unknown client"},
                status_code=401,
            )

        if not application.verify_client_secret(client_secret):
            return JsonResponse(
                {
                    "error": "invalid_client",
                    "error_description": "Invalid client_secret",
                },
                status_code=401,
            )

        return application

    def _handle_authorization_code(self) -> JsonResponse:
        """Exchange an authorization code for tokens."""
        auth_result = self._authenticate_client()
        if isinstance(auth_result, JsonResponse):
            return auth_result
        application = auth_result

        code_value = self.request.form_data.get("code", "")
        redirect_uri = self.request.form_data.get("redirect_uri", "")
        code_verifier = self.request.form_data.get("code_verifier", "")

        if not code_value:
            return _token_error("invalid_request", "Missing code")
        if not code_verifier:
            return _token_error(
                "invalid_request", "Missing code_verifier (PKCE required)"
            )

        try:
            auth_code = AuthorizationCode.query.get(
                code=code_value, application=application
            )
        except AuthorizationCode.DoesNotExist:
            return _token_error("invalid_grant", "Invalid authorization code")

        # Validate the authorization code
        if auth_code.used:
            return _token_error("invalid_grant", "Authorization code already used")

        if auth_code.is_expired():
            return _token_error("invalid_grant", "Authorization code expired")

        if auth_code.redirect_uri != redirect_uri:
            return _token_error("invalid_grant", "redirect_uri mismatch")

        # PKCE verification
        if not auth_code.verify_code_challenge(code_verifier):
            return _token_error("invalid_grant", "PKCE verification failed")

        # Mark code as used (single-use per RFC)
        auth_code.used = True
        auth_code.save(update_fields=["used"])

        # Issue tokens
        return self._issue_tokens(application, auth_code.user, auth_code.scope)

    def _handle_refresh_token(self) -> JsonResponse:
        """Exchange a refresh token for new tokens."""
        auth_result = self._authenticate_client()
        if isinstance(auth_result, JsonResponse):
            return auth_result
        application = auth_result

        refresh_token_value = self.request.form_data.get("refresh_token", "")
        if not refresh_token_value:
            return _token_error("invalid_request", "Missing refresh_token")

        try:
            refresh_token = RefreshToken.query.select_related("access_token").get(
                token=refresh_token_value, application=application
            )
        except RefreshToken.DoesNotExist:
            return _token_error("invalid_grant", "Invalid refresh token")

        if not refresh_token.is_valid():
            return _token_error("invalid_grant", "Refresh token has been revoked")

        # Revoke old tokens (token rotation)
        refresh_token.revoked = True
        refresh_token.save(update_fields=["revoked"])
        refresh_token.access_token.revoked = True
        refresh_token.access_token.save(update_fields=["revoked"])

        # Issue new tokens
        return self._issue_tokens(
            application, refresh_token.user, refresh_token.access_token.scope
        )

    def _issue_tokens(self, application, user, scope) -> JsonResponse:
        """Create a new access token and refresh token pair."""
        expires_at = timezone.now() + timedelta(
            seconds=settings.OAUTH_PROVIDER_ACCESS_TOKEN_EXPIRY
        )

        access_token = AccessToken(
            application=application,
            user=user,
            scope=scope,
            expires_at=expires_at,
        )
        access_token.save()

        refresh_token = RefreshToken(
            application=application,
            user=user,
            access_token=access_token,
        )
        refresh_token.save()

        return JsonResponse(
            {
                "access_token": access_token.token,
                "token_type": "Bearer",
                "expires_in": settings.OAUTH_PROVIDER_ACCESS_TOKEN_EXPIRY,
                "refresh_token": refresh_token.token,
                "scope": scope,
            },
            headers={"Cache-Control": "no-store"},
        )


class RevocationView(View):
    """RFC 7009: Token Revocation.

    Revokes an access token or refresh token.
    """

    def post(self) -> Response:
        client_id = self.request.form_data.get("client_id", "")
        client_secret = self.request.form_data.get("client_secret", "")

        if not client_id or not client_secret:
            return JsonResponse(
                {"error": "invalid_client", "error_description": "Missing credentials"},
                status_code=401,
            )

        try:
            application = OAuthApplication.query.get(client_id=client_id)
        except OAuthApplication.DoesNotExist:
            return JsonResponse(
                {"error": "invalid_client", "error_description": "Unknown client"},
                status_code=401,
            )

        if not application.verify_client_secret(client_secret):
            return JsonResponse(
                {
                    "error": "invalid_client",
                    "error_description": "Invalid client_secret",
                },
                status_code=401,
            )

        token_value = self.request.form_data.get("token", "")
        if not token_value:
            # RFC 7009: server responds with 200 even if token is missing
            return Response(status_code=200)

        # Try access token first, then refresh token
        access_tokens = AccessToken.query.filter(
            token=token_value, application=application
        )
        for at in access_tokens:
            at.revoked = True
            at.save(update_fields=["revoked"])
            return Response(status_code=200)

        refresh_tokens = RefreshToken.query.filter(
            token=token_value, application=application
        )
        for rt in refresh_tokens:
            rt.revoked = True
            rt.save(update_fields=["revoked"])
            # Also revoke the associated access token
            rt.access_token.revoked = True
            rt.access_token.save(update_fields=["revoked"])
            return Response(status_code=200)

        # RFC 7009: respond 200 even if token not found
        return Response(status_code=200)


def _redirect_with_error(redirect_uri: str, error: str, state: str) -> RedirectResponse:
    separator = "&" if "?" in redirect_uri else "?"
    url = f"{redirect_uri}{separator}error={error}"
    if state:
        url += f"&state={state}"
    return RedirectResponse(url, allow_external=True)


def _token_error(error: str, description: str) -> JsonResponse:
    return JsonResponse(
        {"error": error, "error_description": description},
        status_code=400,
    )
