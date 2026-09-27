"""Per-role session cookies and signed double-submit CSRF tokens (ARCHITECTURE
§9.6, C15).

``GET /live/{case}`` (the user) and ``GET /rep/{case}`` (the human rep) each
set a random session cookie (HttpOnly) and a CSRF cookie the page can read,
``HMAC(secret, role, case_id, session)``: the token is bound to the session,
the case and the role, so a cookie injected from elsewhere, another case's
pair or the other role's pair never passes. Every POST echoes the CSRF cookie
in ``X-CSRF-Token``; a WebSocket cannot send a header, so /ws/rep checks the
signed cookie pair alone (its Origin is checked too). All cookies are
SameSite=Strict, Path=/. The secret is made per app and never leaves it.

``GET /start`` issues the operator's pair the same way for ``POST
/api/cases``; it belongs to no case (``NO_CASE``), so its token is bound to
the role and the session only, and never passes as a user or rep pair (nor
theirs as the operator's): the role is in the MAC.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Mapping
from typing import Literal

from starlette.responses import Response

Role = Literal["user", "rep", "operator"]
COOKIES: Mapping[Role, tuple[str, str]] = {  # (session, csrf) per role
    "user": ("pl_session", "pl_csrf"),
    "rep": ("pl_rep_session", "pl_rep_csrf"),
    "operator": ("pl_op_session", "pl_op_csrf"),
}
HEADER = "x-csrf-token"
NO_CASE = ""  # the operator's case_id: never a run id (RUN_ID needs a character)


class Csrf:
    def __init__(self) -> None:
        self._secret = secrets.token_bytes(32)

    def __repr__(self) -> str:  # the secret never reaches a log
        return "Csrf(<secret>)"

    def _token(self, role: Role, case_id: str, session: str) -> str:
        msg = "\x00".join((role, case_id, session)).encode()
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()

    def issue(self, response: Response, role: Role, case_id: str) -> None:
        """Set a new session and its CSRF cookie for ``role`` on ``case_id``."""
        session_name, csrf_name = COOKIES[role]
        session = secrets.token_urlsafe(32)
        token = self._token(role, case_id, session)
        for name, value, private in [
            (session_name, session, True),
            (csrf_name, token, False),  # the page reads it to echo it
        ]:
            response.set_cookie(
                name, value, httponly=private, samesite="strict", path="/"
            )

    def signed(self, role: Role, case_id: str, cookies: Mapping[str, str]) -> bool:
        """The role's cookie pair is present and was issued for this case."""
        session_name, csrf_name = COOKIES[role]
        session, token = cookies.get(session_name), cookies.get(csrf_name)
        if not session or not token:
            return False
        expected = self._token(role, case_id, session).encode()
        return hmac.compare_digest(token.encode(), expected)

    def posted(
        self, role: Role, case_id: str, cookies: Mapping[str, str], header: str | None
    ) -> bool:
        """``signed``, and the header echoes the CSRF cookie (double submit)."""
        token = cookies.get(COOKIES[role][1])
        if header is None or token is None:
            return False
        echoed = hmac.compare_digest(header.encode(), token.encode())
        return echoed and self.signed(role, case_id, cookies)
