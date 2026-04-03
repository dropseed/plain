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
from urllib.parse import urlencode, urlparse, urlunparse

from plain.auth.views import AuthView
from plain.http import JsonResponse, RedirectResponse, Request, Response, ResponseBase
from plain.postgres import transaction
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
        application, errors = self._validate_request()
        if errors:
            context["error"] = errors[0]
            return self._render(context)

        context["application"] = application
        context["scope"] = self.request.query_params.get("scope", "")
        context["redirect_uri"] = self.request.query_params.get("redirect_uri", "")
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
        application, errors = self._validate_request()
        if errors:
            return JsonResponse(
                {"error": "invalid_request", "error_description": errors[0]},
                status_code=400,
            )

        redirect_uri = self.request.form_data.get("redirect_uri", "")
        state = self.request.form_data.get("state", "")

        # User denied
        if self.request.form_data.get("action") != "approve":
            return _redirect_with_params(
                redirect_uri, {"error": "access_denied", "state": state}
            )

        scope = self.request.form_data.get("scope", "")
        code_challenge = self.request.form_data.get("code_challenge", "")
        code_challenge_method = self.request.form_data.get(
            "code_challenge_method", "S256"
        )

        assert application is not None  # guaranteed: no errors means valid client_id

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

        params = {"code": auth_code.code}
        if state:
            params["state"] = state

        return _redirect_with_params(redirect_uri, params)

    def _validate_request(self) -> tuple[OAuthApplication | None, list[str]]:
        """Validate the authorization request parameters.

        Returns (application, errors). Application is None if validation fails.
        """
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

        application = None
        client_id = params.get("client_id", "")
        if not client_id:
            errors.append("Missing client_id")
        else:
            try:
                application = OAuthApplication.query.get(client_id=client_id)
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

        return application, errors


class TokenView(View):
    """OAuth 2.1 Token Endpoint.

    Handles:
    - authorization_code grant (with PKCE verification)
    - refresh_token grant
    """

    def post(self) -> JsonResponse:
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

    def _handle_authorization_code(self) -> JsonResponse:
        """Exchange an authorization code for tokens."""
        auth_result = _authenticate_client(self.request)
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

        if auth_code.used:
            return _token_error("invalid_grant", "Authorization code already used")

        if auth_code.is_expired():
            return _token_error("invalid_grant", "Authorization code expired")

        if auth_code.redirect_uri != redirect_uri:
            return _token_error("invalid_grant", "redirect_uri mismatch")

        if not auth_code.verify_code_challenge(code_verifier):
            return _token_error("invalid_grant", "PKCE verification failed")

        # Mark code as used (single-use per RFC)
        auth_code.used = True
        auth_code.save(update_fields=["used"])

        return _issue_tokens(application, auth_code.user, auth_code.scope)

    def _handle_refresh_token(self) -> JsonResponse:
        """Exchange a refresh token for new tokens."""
        auth_result = _authenticate_client(self.request)
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

        return _issue_tokens(
            application, refresh_token.user, refresh_token.access_token.scope
        )


class RevocationView(View):
    """RFC 7009: Token Revocation.

    Revokes an access token or refresh token.
    """

    def post(self) -> Response:
        auth_result = _authenticate_client(self.request)
        if isinstance(auth_result, JsonResponse):
            return auth_result
        application = auth_result

        token_value = self.request.form_data.get("token", "")
        if not token_value:
            # RFC 7009: server responds with 200 even if token is missing
            return Response(status_code=200)

        # Try access token first, then refresh token
        revoked = AccessToken.query.filter(
            token=token_value, application=application
        ).update(revoked=True)
        if revoked:
            return Response(status_code=200)

        try:
            rt = RefreshToken.query.select_related("access_token").get(
                token=token_value, application=application
            )
        except RefreshToken.DoesNotExist:
            # RFC 7009: respond 200 even if token not found
            return Response(status_code=200)

        rt.revoked = True
        rt.save(update_fields=["revoked"])
        AccessToken.query.filter(id=rt.access_token.id).update(revoked=True)

        return Response(status_code=200)


def _authenticate_client(request: Request) -> OAuthApplication | JsonResponse:
    """Authenticate the client via client_secret_post."""
    client_id = request.form_data.get("client_id", "")
    client_secret = request.form_data.get("client_secret", "")

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


def _issue_tokens(
    application: OAuthApplication, user: object, scope: str
) -> JsonResponse:
    """Create a new access token and refresh token pair."""
    expires_at = timezone.now() + timedelta(
        seconds=settings.OAUTH_PROVIDER_ACCESS_TOKEN_EXPIRY
    )

    with transaction.atomic():
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


def _redirect_with_params(
    redirect_uri: str, params: dict[str, str]
) -> RedirectResponse:
    """Append query parameters to a redirect URI."""
    # Filter out empty values
    params = {k: v for k, v in params.items() if v}
    parsed = urlparse(redirect_uri)
    separator = "&" if parsed.query else ""
    new_query = parsed.query + separator + urlencode(params)
    url = urlunparse(parsed._replace(query=new_query))
    return RedirectResponse(url, allow_external=True)


def _token_error(error: str, description: str) -> JsonResponse:
    return JsonResponse(
        {"error": error, "error_description": description},
        status_code=400,
    )
