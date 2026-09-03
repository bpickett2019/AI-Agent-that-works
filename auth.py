"""Microsoft Entra authorization-code authentication and server-side role checks."""
from __future__ import annotations

import hmac
import os
import secrets
from dataclasses import dataclass
from typing import Any

import msal
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse


@dataclass(frozen=True)
class Identity:
    subject: str
    email: str
    display_name: str
    roles: tuple[str, ...]
    is_admin: bool

    def session_value(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "email": self.email,
            "display_name": self.display_name,
            "roles": list(self.roles),
            "is_admin": self.is_admin,
        }


class EntraAuth:
    def __init__(self) -> None:
        self.environment = os.environ.get("CVENT_ENV", "development")
        self.tenant_id = os.environ.get("ENTRA_TENANT_ID", "")
        self.client_id = os.environ.get("ENTRA_CLIENT_ID", "")
        self.client_secret = os.environ.get("ENTRA_CLIENT_SECRET", "")
        self.user_role = os.environ.get("CVENT_USER_APP_ROLE", "Cvent.Agent.User")
        self.admin_role = os.environ.get("CVENT_ADMIN_APP_ROLE", "Cvent.Agent.Admin")
        self.authority = f"https://login.microsoftonline.com/{self.tenant_id}" if self.tenant_id else ""
        self.router = APIRouter()
        self.router.add_api_route("/auth/login", self.login, methods=["GET"])
        self.router.add_api_route("/auth/callback", self.callback, methods=["GET"], name="entra_callback")
        self.router.add_api_route("/auth/logout", self.logout, methods=["POST"])

    @property
    def configured(self) -> bool:
        return bool(self.tenant_id and self.client_id and self.client_secret)

    def client(self) -> msal.ConfidentialClientApplication:
        if not self.configured:
            raise HTTPException(503, "Microsoft Entra authentication is not configured")
        return msal.ConfidentialClientApplication(
            self.client_id, authority=self.authority, client_credential=self.client_secret
        )

    def redirect_uri(self, request: Request) -> str:
        configured = os.environ.get("ENTRA_REDIRECT_URI")
        return configured or str(request.url_for("entra_callback"))

    async def login(self, request: Request):
        flow = self.client().initiate_auth_code_flow(
            scopes=[], redirect_uri=self.redirect_uri(request), prompt="select_account"
        )
        request.session["entra_flow"] = flow
        return RedirectResponse(flow["auth_uri"], status_code=302)

    async def callback(self, request: Request):
        flow = request.session.pop("entra_flow", None)
        if not flow:
            raise HTTPException(400, "Authentication flow expired; start login again")
        try:
            result = self.client().acquire_token_by_auth_code_flow(flow, dict(request.query_params))
        except ValueError as exc:
            raise HTTPException(400, "Microsoft Entra state validation failed") from exc
        claims = result.get("id_token_claims") or {}
        if "error" in result or claims.get("tid") != self.tenant_id:
            raise HTTPException(403, result.get("error_description", "Microsoft Entra authentication failed"))
        roles = tuple(str(role) for role in claims.get("roles", []))
        if self.user_role not in roles and self.admin_role not in roles:
            raise HTTPException(403, "Your account is not assigned to the CVENT Agent application")
        oid = claims.get("oid")
        if not oid:
            raise HTTPException(403, "Microsoft Entra token has no object identifier")
        identity = Identity(
            subject=f"{self.tenant_id}:{oid}",
            email=str(claims.get("preferred_username") or claims.get("email") or ""),
            display_name=str(claims.get("name") or claims.get("preferred_username") or "CVENT user"),
            roles=roles,
            is_admin=self.admin_role in roles,
        )
        request.session.clear()
        request.session["identity"] = identity.session_value()
        request.session["csrf"] = secrets.token_urlsafe(32)
        return RedirectResponse("/", status_code=303)

    async def logout(self, request: Request):
        self.validate_csrf(request)
        request.session.clear()
        return RedirectResponse(
            f"{self.authority}/oauth2/v2.0/logout?post_logout_redirect_uri={request.base_url}", status_code=303
        )

    def identity(self, request: Request) -> Identity:
        value = request.session.get("identity")
        if value:
            return Identity(
                subject=str(value["subject"]),
                email=str(value.get("email", "")),
                display_name=str(value.get("display_name", "")),
                roles=tuple(value.get("roles", [])),
                is_admin=bool(value.get("is_admin")),
            )
        if self.environment == "development" and os.environ.get("CVENT_DEV_AUTH_SUBJECT"):
            is_admin = os.environ.get("CVENT_DEV_AUTH_ADMIN", "0") == "1"
            identity = Identity(
                subject="dev:" + os.environ["CVENT_DEV_AUTH_SUBJECT"],
                email=os.environ.get("CVENT_DEV_AUTH_EMAIL", "developer@localhost"),
                display_name=os.environ.get("CVENT_DEV_AUTH_NAME", "Local developer"),
                roles=(self.user_role, self.admin_role) if is_admin else (self.user_role,),
                is_admin=is_admin,
            )
            request.session["identity"] = identity.session_value()
            request.session.setdefault("csrf", secrets.token_urlsafe(32))
            return identity
        raise HTTPException(401, "Sign in with Microsoft Entra ID")

    def require_admin(self, request: Request) -> Identity:
        identity = self.identity(request)
        if not identity.is_admin:
            raise HTTPException(403, "Administrator role required")
        return identity

    def validate_csrf(self, request: Request) -> None:
        expected = request.session.get("csrf", "")
        supplied = request.headers.get("x-csrf-token", "")
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            raise HTTPException(403, "CSRF validation failed")

    def me(self, request: Request) -> dict[str, Any]:
        identity = self.identity(request)
        return {**identity.session_value(), "csrf": request.session["csrf"]}
