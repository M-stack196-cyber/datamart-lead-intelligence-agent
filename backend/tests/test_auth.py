import pytest
from fastapi import HTTPException

from app.api.auth import require_user
from app.core.config import Settings


@pytest.mark.anyio
async def test_require_user_rejects_missing_supabase_configuration() -> None:
    with pytest.raises(HTTPException) as exc:
        await require_user(credentials=None, settings=Settings(_env_file=None))
    assert exc.value.status_code == 503


@pytest.mark.anyio
async def test_require_user_rejects_missing_bearer_token_when_configured() -> None:
    settings = Settings(
        _env_file=None,
        supabase_url="https://example.supabase.co",
        supabase_anon_key="public-anon-key",
    )
    with pytest.raises(HTTPException) as exc:
        await require_user(credentials=None, settings=settings)
    assert exc.value.status_code == 401
