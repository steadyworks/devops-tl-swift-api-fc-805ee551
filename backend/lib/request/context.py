import logging
from enum import Enum
from typing import Optional, Self
from uuid import UUID, uuid4

from fastapi import HTTPException, Request, WebSocket, WebSocketException
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.status import (
    HTTP_401_UNAUTHORIZED,
    WS_1008_POLICY_VIOLATION,
)

from backend.db.dal import (
    DALOwnerIdentities,
    DALOwners,
    DAOOwnerIdentitiesCreate,
    DAOOwnersCreate,
    FilterOp,
    safe_transaction,
)

# These two should already exist after your migration. If names differ, adjust.
from backend.db.data_models import DAOUsers, IdentityKind
from backend.env_loader import EnvLoader

SUPABASE_JWT_SECRET = EnvLoader.get("SUPABASE_JWT_SECRET")
SUPABASE_JWT_ALGO = "HS256"

if not SUPABASE_JWT_SECRET:
    raise RuntimeError("Missing SUPABASE_JWT_SECRET env var")


class SupabaseJWTClaims(BaseModel):
    sub: str  # maps to auth.users.id and public.users.id (UUID)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    role: str
    iss: Optional[str] = None
    # You can extend with app_metadata, user_metadata if needed


class AuthMode(str, Enum):
    USER = "user"
    GUEST = "guest"


class RequestContext:
    """
    Minimal, single-source-of-truth context:
    - Always has an owner_id
    - Optionally has a Supabase user (mode=USER) or a guest_id (mode=GUEST)
    """

    def __init__(
        self,
        *,
        mode: AuthMode,
        owner_id: UUID,
        request_id: UUID = uuid4(),
        # Optional user/guest extras
        raw_token: Optional[str] = None,
        claims: Optional[SupabaseJWTClaims] = None,
        user_id: Optional[UUID] = None,
        guest_id: Optional[UUID] = None,
        user_row: Optional[DAOUsers] = None,
    ) -> None:
        self._mode = mode
        self._owner_id = owner_id
        self._request_id = request_id
        self._raw_token = raw_token
        self._claims = claims
        self._user_id = user_id
        self._guest_id = guest_id
        self._user_row = user_row

    # ------------ Properties (kept close to your originals) ------------

    @property
    def mode(self) -> AuthMode:
        return self._mode

    @property
    def owner_id(self) -> UUID:
        return self._owner_id

    @property
    def user_id_assert_logged_in(self) -> UUID:
        """Returns user_id when authenticated; None for guests."""
        if self._user_id is None:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="User not logged in",
            )
        return self._user_id

    @property
    def email(self) -> Optional[str]:
        if self._user_row and self._user_row.email:
            return self._user_row.email
        return self._claims.email if self._claims else None

    @property
    def role(self) -> Optional[str]:
        if self._user_row and getattr(self._user_row, "role", None):
            return self._user_row.role
        return self._claims.role if self._claims else None

    @property
    def name(self) -> Optional[str]:
        return self._user_row.name if self._user_row else None

    @property
    def user(self) -> Optional[DAOUsers]:
        return self._user_row

    @property
    def request_id(self) -> UUID:
        return self._request_id

    # ----------------------- Factory: HTTP request -----------------------

    @classmethod
    async def from_request(
        cls,
        request: Request,
        db_session: AsyncSession,
    ) -> Self:
        # Cache per-request
        if hasattr(request.state, "ctx"):
            return request.state.ctx

        if not hasattr(request.state, "request_id"):
            request.state.request_id = uuid4()
        request_id: UUID = request.state.request_id

        # Prefer Supabase JWT if present
        token = None
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header.removeprefix("Bearer ").strip()

        # If token present, try decode → USER
        if token:
            claims, user_id = _try_decode_supabase(token)
            if user_id:
                async with safe_transaction(
                    db_session, "create owner + identity", raise_on_fail=True
                ):
                    user_row: Optional[DAOUsers] = None
                    from backend.db.dal import DALUsers  # avoid circular imports

                    try:
                        user_row = await DALUsers.get_by_id(db_session, user_id)
                    except Exception as _e:
                        raise HTTPException(
                            status_code=HTTP_401_UNAUTHORIZED,
                            detail="Invalid user ID",
                        )

                    owner_id = await _ensure_owner_for_user(db_session, user_id)

                    ctx = cls(
                        mode=AuthMode.USER,
                        owner_id=owner_id,
                        request_id=request_id,
                        raw_token=token,
                        claims=claims,
                        user_id=user_id,
                        user_row=user_row,
                    )
                    request.state.ctx = ctx
                    return ctx

            # If token provided but invalid → reject (keeps semantics strict)
            logging.warning("JWT decode failed or invalid sub")
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
            )

        # Else, guest via X-Guest-Id
        guest_raw = request.headers.get("x-guest-id")
        guest_id = _parse_uuid_or_none(guest_raw)
        if guest_id:
            async with safe_transaction(
                db_session, "create owner + identity", raise_on_fail=True
            ):
                owner_id = await _ensure_owner_for_guest(db_session, guest_id)
                ctx = cls(
                    mode=AuthMode.GUEST,
                    owner_id=owner_id,
                    request_id=request_id,
                    guest_id=guest_id,
                )
                request.state.ctx = ctx
                return ctx

        # No creds
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Missing credentials (Authorization or X-Guest-Id)",
        )

    # ----------------------- Factory: WebSocket -----------------------

    @classmethod
    async def from_websocket(
        cls,
        websocket: WebSocket,
        db_session: AsyncSession,
    ) -> Self:
        """
        Accepts:
          - token=<supabase_jwt> query param OR Authorization: Bearer <jwt>
          - OR guest_id=<uuid> query param OR X-Guest-Id header
        """
        request_id = uuid4()

        # 1) Try token (query or header)
        token = websocket.query_params.get("token")
        if not token:
            auth_header = websocket.headers.get("authorization")
            if auth_header and auth_header.lower().startswith("bearer "):
                token = auth_header.removeprefix("Bearer ").strip()

        if token:
            try:
                decoded = jwt.decode(
                    token,
                    SUPABASE_JWT_SECRET,
                    algorithms=[SUPABASE_JWT_ALGO],
                    audience="authenticated",
                )
                claims = SupabaseJWTClaims.model_validate(decoded)
                user_id = UUID(claims.sub)
            except (JWTError, ValidationError, ValueError) as e:
                logging.warning("[WS][%s] Invalid auth token: %s", request_id, e)
                raise WebSocketException(
                    code=WS_1008_POLICY_VIOLATION, reason="Invalid authentication token"
                )

            async with safe_transaction(
                db_session, "create owner + identity", raise_on_fail=True
            ):
                # Optionally load user row
                user_row: Optional[DAOUsers] = None
                try:
                    from backend.db.dal import DALUsers  # avoid circular import

                    user_row = await DALUsers.get_by_id(db_session, user_id)
                except Exception as _e:
                    raise HTTPException(
                        status_code=HTTP_401_UNAUTHORIZED,
                        detail="Invalid user ID",
                    )

                owner_id = await _ensure_owner_for_user(db_session, user_id)
                return cls(
                    mode=AuthMode.USER,
                    owner_id=owner_id,
                    request_id=request_id,
                    raw_token=token,
                    claims=claims,
                    user_id=user_id,
                    user_row=user_row,
                )

        # 2) Try guest
        guest_raw = websocket.query_params.get("guest_id") or websocket.headers.get(
            "x-guest-id"
        )
        guest_id = _parse_uuid_or_none(guest_raw)
        if guest_id:
            async with safe_transaction(
                db_session, "create owner + identity", raise_on_fail=True
            ):
                owner_id = await _ensure_owner_for_guest(db_session, guest_id)
                return cls(
                    mode=AuthMode.GUEST,
                    owner_id=owner_id,
                    request_id=request_id,
                    guest_id=guest_id,
                )

        # 3) No creds
        logging.warning("[WS][%s] Missing credentials", request_id)
        raise WebSocketException(
            code=WS_1008_POLICY_VIOLATION,
            reason="Missing credentials (token or guest_id / X-Guest-Id)",
        )


# ----------------------- Helpers -----------------------


def _try_decode_supabase(
    token: str,
) -> tuple[Optional[SupabaseJWTClaims], Optional[UUID]]:
    try:
        decoded = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=[SUPABASE_JWT_ALGO],
            audience="authenticated",
        )
        claims = SupabaseJWTClaims.model_validate(decoded)
        return claims, UUID(claims.sub)
    except (JWTError, ValidationError, ValueError):
        return None, None


def _parse_uuid_or_none(s: Optional[str]) -> Optional[UUID]:
    if not s:
        return None
    try:
        return UUID(s)
    except Exception:
        return None


async def _ensure_owner_for_user(db_session: AsyncSession, user_id: UUID) -> UUID:
    """
    Find or create an owner bound to this Supabase user.
    """
    res = await DALOwnerIdentities.list_all(
        db_session,
        {
            "kind": (FilterOp.EQ, IdentityKind.USER),
            "identity": (FilterOp.EQ, user_id),
        },
        1,
    )
    if res:
        return res[0].owner_id

    owner_dao = await DALOwners.create(db_session, DAOOwnersCreate())
    await DALOwnerIdentities.create(
        db_session,
        DAOOwnerIdentitiesCreate(
            owner_id=owner_dao.id,
            kind=IdentityKind.USER,
            identity=user_id,
        ),
    )
    return owner_dao.id


async def _ensure_owner_for_guest(db_session: AsyncSession, guest_id: UUID) -> UUID:
    """
    Find or create an owner bound to this guest UUID.
    """
    res = await DALOwnerIdentities.list_all(
        db_session,
        {
            "kind": (FilterOp.EQ, IdentityKind.GUEST),
            "identity": (FilterOp.EQ, guest_id),
        },
        1,
    )
    if res:
        return res[0].owner_id

    owner_dao = await DALOwners.create(db_session, DAOOwnersCreate())
    await DALOwnerIdentities.create(
        db_session,
        DAOOwnerIdentitiesCreate(
            owner_id=owner_dao.id,
            kind=IdentityKind.GUEST,
            identity=guest_id,
        ),
    )
    return owner_dao.id
