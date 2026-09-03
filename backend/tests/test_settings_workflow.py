from pathlib import Path


def test_settings_route_uses_settings_workspace() -> None:
    page = (Path(__file__).parents[2] / "frontend" / "src" / "app" / "[section]" / "page.tsx").read_text()
    assert "SettingsWorkspace" in page
    assert 'if (section === "settings")' in page


def test_settings_workspace_lists_audit_and_role_controls() -> None:
    component = (Path(__file__).parents[2] / "frontend" / "src" / "components" / "settings-workspace.tsx").read_text()
    assert "audit_log" in component
    assert "role" in component.lower()
