from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client, create_client

from app.core.config import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    role: str


def _verify_user(client: Client, token: str) -> tuple[object, object]:
    user_response = client.auth.get_user(token)
    user = user_response.user
    profile = client.table("profiles").select("role, is_active").eq("id", user.id).single().execute().data
    return user, profile


async def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """Validate a Supabase access token and load the server-trusted application role."""
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Supabase authentication is not configured")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    try:
        client = create_client(settings.supabase_url, settings.supabase_anon_key)
        user, profile = await run_in_threadpool(_verify_user, client, credentials.credentials)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token") from exc

    if not profile or not profile.get("is_active"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")
    return CurrentUser(id=str(user.id), email=user.email or "", role=str(profile["role"]))


def require_roles(*allowed_roles: str):
    async def dependency(user: CurrentUser = Depends(require_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return dependency
