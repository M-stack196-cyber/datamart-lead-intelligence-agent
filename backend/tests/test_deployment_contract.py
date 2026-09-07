from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_root_dotenv_example_lists_required_runtime_variables() -> None:
    content = (ROOT / ".env.example").read_text()

    required = {
        "NEXT_PUBLIC_SUPABASE_URL",
        "NEXT_PUBLIC_SUPABASE_ANON_KEY",
        "APP_ENV",
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "DATABASE_URL",
        "CORS_ORIGINS",
        "FRONTEND_URL",
        "BACKEND_URL",
        "VIBE_API_KEY",
        "AWS_BEARER_TOKEN_BEDROCK",
        "OUTBOUND_EMAIL_PROVIDER",
        "OUTBOUND_REPLY_PROVIDER",
        "OUTBOUND_CRM_PROVIDER",
    }

    for key in required:
        assert key in content, f"Missing deployment variable: {key}"


def test_vercel_services_config_mounts_frontend_and_backend() -> None:
    config = (ROOT / "vercel.json").read_text()

    assert '"services"' in config
    assert '"frontend"' in config
    assert '"root": "frontend/"' in config
    assert '"framework": "nextjs"' in config

    assert '"backend"' in config
    assert '"root": "backend/"' in config
    assert '"entrypoint": "app.main:app"' in config

    assert '"/api/:path*"' in config
    assert '"service": "backend"' in config


def test_fastapi_uses_api_root_path_in_production() -> None:
    main_py = (ROOT / "backend" / "app" / "main.py").read_text()

    assert 'root_path="/api" if settings.app_env == "production" else ""' in main_py
    assert "app.include_router(router)" in main_py
    assert 'prefix="/api"' not in main_py


def test_frontend_uses_same_origin_api_in_production() -> None:
    files = [
        ROOT / "frontend" / "src" / "components" / "outreach-draft-panel.tsx",
        ROOT / "frontend" / "src" / "components" / "outreach-workspace.tsx",
    ]

    expected = (
        'process.env.NEXT_PUBLIC_API_URL || '
        '(process.env.NODE_ENV === "production" ? "/api" : "http://localhost:8000")'
    )

    for path in files:
        assert expected in path.read_text()
