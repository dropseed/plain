"""OAuth 2.1 authorization server.

Implements the subset of OAuth 2.1 an MCP client (e.g. Claude's custom
connector) needs to authenticate an end user against a Plain app:

- Authorization server metadata (RFC 8414)
- Dynamic client registration (RFC 7591) — public clients, PKCE
- Authorization code grant with PKCE (RFC 7636), audience-bound (RFC 8707)
- Token endpoint with refresh-token rotation (RFC 6749, OAuth 2.1)
- Token revocation (RFC 7009)
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

from plain.auth.views import AuthView
from plain.http import JsonResponse, RedirectResponse, Request, Response
from plain.postgres import transaction
from plain.runtime import settings
from plain.templates import Template
from plain.urls import reverse
from plain.utils import timezone
from plain.views import View

from .models import (
    _LOOPBACK_HOSTS,
    AccessToken,
    AuthorizationCode,
    OAuthApplication,
    RefreshToken,
    _generate_token,
    _hash_token,
)

_GRANT_TYPES = ["authorization_code", "refresh_token"]
_RESPONSE_TYPES = ["code"]


def _issuer(request: Request) -> str:
    # request.scheme is proxy-aware (X-Forwarded-Proto), matching build_absolute_uri.
    return f"{request.scheme}://{request.host}"


def _is_allowed_redirect_uri(uri: str) -> bool:
    """OAuth 2.1: redirect URIs must be HTTPS, or loopback for native clients."""
    # Reject whitespace and fragments: redirect_uris are stored space-joined, so a
    # value containing whitespace would smuggle in a second, unvalidated URI.
    if any(c.isspace() for c in uri):
        return False
    parsed = urlparse(uri)
    if parsed.fragment:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname in _LOOPBACK_HOSTS


class AuthorizationServerMetadataView(View):
    """RFC 8414 — served at /.well-known/oauth-authorization-server."""

    def get(self) -> JsonResponse:
        issuer = _issuer(self.request)
        metadata: dict[str, Any] = {
            "issuer": issuer,
            "authorization_endpoint": issuer + reverse("oauthserver:authorize"),
            "token_endpoint": issuer + reverse("oauthserver:token"),
            "revocation_endpoint": issuer + reverse("oauthserver:revoke"),
            "response_types_supported": _RESPONSE_TYPES,
            "grant_types_supported": _GRANT_TYPES,
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": list(settings.OAUTH_SERVER_SCOPES_SUPPORTED),
        }
        if settings.OAUTH_SERVER_ALLOW_DYNAMIC_REGISTRATION:
            metadata["registration_endpoint"] = issuer + reverse("oauthserver:register")
        return JsonResponse(metadata)


class RegisterView(View):
    """RFC 7591 — dynamic client registration.

    Open registration: a freshly registered client can do nothing until a real
    user completes the authorization + consent flow, so the risk is bounded.
    """

    def post(self) -> JsonResponse:
        if not settings.OAUTH_SERVER_ALLOW_DYNAMIC_REGISTRATION:
            return _oauth_error(
                "invalid_request", "Dynamic registration is disabled", status_code=403
            )

        metadata = self.request.json_data
        if not isinstance(metadata, dict):
            return _oauth_error("invalid_client_metadata", "Body must be a JSON object")

        redirect_uris = metadata.get("redirect_uris")
        if not isinstance(redirect_uris, list) or not redirect_uris:
            return _oauth_error("invalid_redirect_uri", "redirect_uris is required")
        if not all(
            isinstance(u, str) and _is_allowed_redirect_uri(u) for u in redirect_uris
        ):
            return _oauth_error(
                "invalid_redirect_uri", "redirect_uris must be HTTPS or loopback"
            )

        # Every client is public (PKCE-proven); we never issue a secret, so any
        # requested token_endpoint_auth_method is overridden to "none".
        application = OAuthApplication(
            name=metadata.get("client_name", ""),
            redirect_uris=" ".join(redirect_uris),
        )
        application.create()

        return JsonResponse(
            {
                "client_id": application.client_id,
                "client_id_issued_at": int(application.created_at.timestamp()),
                "redirect_uris": redirect_uris,
                "token_endpoint_auth_method": "none",
                "grant_types": _GRANT_TYPES,
                "response_types": _RESPONSE_TYPES,
                "client_name": application.name,
            },
            status_code=201,
            headers={"Cache-Control": "no-store"},
        )


class AuthorizeView(AuthView):
    """Authorization endpoint. GET shows consent; POST records the decision."""

    login_required = True

    def get(self) -> Response:
        application, error = self._validate_request(self.request.query_params)
        if error:
            return self._render({"error": error})

        params = self.request.query_params
        return self._render(
            {
                "application": application,
                "scope": params.get("scope", ""),
                "params": {
                    "response_type": "code",
                    "client_id": params.get("client_id", ""),
                    "redirect_uri": params.get("redirect_uri", ""),
                    "scope": params.get("scope", ""),
                    "state": params.get("state", ""),
                    "resource": params.get("resource", ""),
                    "code_challenge": params.get("code_challenge", ""),
                    "code_challenge_method": params.get("code_challenge_method")
                    or "S256",
                },
            }
        )

    def post(self) -> Response:
        form = self.request.form_data
        application, error = self._validate_request(form)
        if error:
            return JsonResponse(
                {"error": "invalid_request", "error_description": error},
                status_code=400,
            )
        assert application is not None  # a None error implies a valid client

        # redirect_uri was validated against the client by _validate_request,
        # so it's safe to redirect back to.
        redirect_uri = form.get("redirect_uri", "")
        state = form.get("state", "")

        if form.get("action") != "approve":
            return _redirect(redirect_uri, {"error": "access_denied", "state": state})

        auth_code = AuthorizationCode(
            application=application,
            user=self.user,
            redirect_uri=redirect_uri,
            scope=form.get("scope", ""),
            resource=form.get("resource", ""),
            code_challenge=form.get("code_challenge", ""),
            expires_at=timezone.now()
            + timedelta(seconds=settings.OAUTH_SERVER_CODE_EXPIRY),
        )
        auth_code.create()

        return _redirect(
            redirect_uri,
            {"code": auth_code.code, "state": state, "iss": _issuer(self.request)},
        )

    def _render(self, context: dict[str, Any]) -> Response:
        # Always supply every variable the template reads (Jinja runs in strict
        # mode), so the template needs no `is defined` guards.
        full = {
            "request": self.request,
            "error": None,
            "application": None,
            "scope": "",
            "params": {},
            **context,
        }
        html = Template("oauthserver/authorize.html").render(full)
        return Response(html, content_type="text/html")

    def _validate_request(
        self, params: Any
    ) -> tuple[OAuthApplication | None, str | None]:
        """Validate an authorization request. Returns (application, error).

        Stops at the first problem. `application` is set once the client
        resolves, so a redirect-back is only ever attempted against a URI
        already proven to belong to that client.
        """
        if params.get("response_type", "") != "code":
            return None, "response_type must be 'code'"

        client_id = params.get("client_id", "")
        if not client_id:
            return None, "Missing client_id"
        try:
            application = OAuthApplication.query.get(client_id=client_id)
        except OAuthApplication.DoesNotExist:
            return None, f"Unknown client_id: {client_id}"

        # Validate the redirect target before anything else can act on it —
        # OAuth 2.1 §4.1.2.1 says to inform the user here, not redirect.
        if not application.is_valid_redirect_uri(params.get("redirect_uri", "")):
            return application, "Invalid redirect_uri"

        if not params.get("code_challenge", ""):
            return application, "Missing code_challenge (PKCE is required)"
        method = params.get("code_challenge_method", "")
        if method and method != "S256":
            return application, "code_challenge_method must be 'S256'"

        # Don't grant scopes the app never advertised — a consumer gating tools
        # on scopes would otherwise treat an unconfigured scope as granted.
        supported = set(settings.OAUTH_SERVER_SCOPES_SUPPORTED)
        unsupported = [s for s in params.get("scope", "").split() if s not in supported]
        if unsupported:
            return application, f"Unsupported scope(s): {' '.join(unsupported)}"

        return application, None


class TokenView(View):
    """Token endpoint — authorization_code and refresh_token grants."""

    def post(self) -> JsonResponse:
        grant_type = self.request.form_data.get("grant_type", "")
        match grant_type:
            case "authorization_code":
                return self._authorization_code()
            case "refresh_token":
                return self._refresh_token()
            case _:
                return _oauth_error(
                    "unsupported_grant_type", f"Unsupported grant_type: {grant_type!r}"
                )

    def _authorization_code(self) -> JsonResponse:
        application = _resolve_client(self.request)
        if isinstance(application, JsonResponse):
            return application

        form = self.request.form_data
        code_value = form.get("code", "")
        code_verifier = form.get("code_verifier", "")
        if not code_value:
            return _oauth_error("invalid_request", "Missing code")
        if not code_verifier:
            return _oauth_error(
                "invalid_request", "Missing code_verifier (PKCE required)"
            )

        # Lock the code row so two concurrent exchanges can't both spend it.
        with transaction.atomic():
            try:
                auth_code = AuthorizationCode.query.select_for_update().get(
                    code=code_value, application=application
                )
            except AuthorizationCode.DoesNotExist:
                return _oauth_error("invalid_grant", "Invalid authorization code")

            if auth_code.used:
                return _oauth_error("invalid_grant", "Authorization code already used")
            if auth_code.is_expired():
                return _oauth_error("invalid_grant", "Authorization code expired")
            if auth_code.redirect_uri != form.get("redirect_uri", ""):
                return _oauth_error("invalid_grant", "redirect_uri mismatch")
            if not auth_code.verify_code_challenge(code_verifier):
                return _oauth_error("invalid_grant", "PKCE verification failed")

            auth_code.used = True
            auth_code.update(fields=["used"])

            return _issue_tokens(
                application, auth_code.user, auth_code.scope, auth_code.resource
            )

    def _refresh_token(self) -> JsonResponse:
        application = _resolve_client(self.request)
        if isinstance(application, JsonResponse):
            return application

        token_value = self.request.form_data.get("refresh_token", "")
        if not token_value:
            return _oauth_error("invalid_request", "Missing refresh_token")

        # Lock the row so concurrent reuse of one refresh token can't fork into
        # two valid token pairs — the second waits, then sees it revoked.
        with transaction.atomic():
            try:
                refresh = (
                    RefreshToken.query.select_for_update()
                    .select_related("access_token")
                    .get(token_hash=_hash_token(token_value), application=application)
                )
            except RefreshToken.DoesNotExist:
                return _oauth_error("invalid_grant", "Invalid refresh token")

            if not refresh.is_valid():
                return _oauth_error("invalid_grant", "Refresh token is no longer valid")

            # Carry the grant forward from the old access token before revoking it.
            scope = refresh.access_token.scope
            resource = refresh.access_token.resource

            # Rotate: invalidate the old pair before issuing a new one.
            refresh.revoked = True
            refresh.update(fields=["revoked"])
            refresh.access_token.revoked = True
            refresh.access_token.update(fields=["revoked"])

            return _issue_tokens(application, refresh.user, scope, resource)


class RevocationView(View):
    """RFC 7009 — always responds 200, even for unknown tokens."""

    def post(self) -> Response:
        application = _resolve_client(self.request)
        if isinstance(application, JsonResponse):
            return application

        token_value = self.request.form_data.get("token", "")
        if not token_value:
            return Response(status_code=200)
        token_hash = _hash_token(token_value)

        revoked = AccessToken.query.filter(
            token_hash=token_hash, application=application
        ).update(revoked=True)
        if revoked:
            return Response(status_code=200)

        try:
            refresh = RefreshToken.query.get(
                token_hash=token_hash, application=application
            )
        except RefreshToken.DoesNotExist:
            return Response(status_code=200)

        refresh.revoked = True
        refresh.update(fields=["revoked"])
        AccessToken.query.filter(id=refresh.access_token.id).update(revoked=True)
        return Response(status_code=200)


def _resolve_client(request: Request) -> OAuthApplication | JsonResponse:
    """Look up the public client by client_id (PKCE / the refresh token is the proof)."""
    client_id = request.form_data.get("client_id", "")
    if not client_id:
        return _oauth_error("invalid_client", "Missing client_id", status_code=401)

    try:
        return OAuthApplication.query.get(client_id=client_id)
    except OAuthApplication.DoesNotExist:
        return _oauth_error("invalid_client", "Unknown client", status_code=401)


def _issue_tokens(
    application: OAuthApplication, user: Any, scope: str, resource: str
) -> JsonResponse:
    # Both callers run inside the transaction that locked the code/refresh row,
    # so these two inserts are already atomic with the rotation.
    access_value = _generate_token()
    refresh_value = _generate_token()
    now = timezone.now()

    access_token = AccessToken(
        application=application,
        user=user,
        scope=scope,
        resource=resource,
        token_hash=_hash_token(access_value),
        expires_at=now + timedelta(seconds=settings.OAUTH_SERVER_ACCESS_TOKEN_EXPIRY),
    )
    access_token.create()
    refresh_token = RefreshToken(
        application=application,
        user=user,
        access_token=access_token,
        token_hash=_hash_token(refresh_value),
        expires_at=now + timedelta(seconds=settings.OAUTH_SERVER_REFRESH_TOKEN_EXPIRY),
    )
    refresh_token.create()

    return JsonResponse(
        {
            "access_token": access_value,
            "token_type": "Bearer",
            "expires_in": settings.OAUTH_SERVER_ACCESS_TOKEN_EXPIRY,
            "refresh_token": refresh_value,
            "scope": scope,
        },
        headers={"Cache-Control": "no-store"},
    )


def _redirect(redirect_uri: str, params: dict[str, str]) -> RedirectResponse:
    params = {k: v for k, v in params.items() if v}
    parsed = urlparse(redirect_uri)
    separator = "&" if parsed.query else ""
    new_query = parsed.query + separator + urlencode(params)
    return RedirectResponse(
        urlunparse(parsed._replace(query=new_query)), allow_external=True
    )


def _oauth_error(
    error: str, description: str, *, status_code: int = 400
) -> JsonResponse:
    """An RFC 6749 error response (`{"error", "error_description"}`)."""
    return JsonResponse(
        {"error": error, "error_description": description}, status_code=status_code
    )
