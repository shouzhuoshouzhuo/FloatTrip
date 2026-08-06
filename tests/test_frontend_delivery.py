from fastapi.testclient import TestClient

from app.main import app


def test_frontend_html_disables_cache_and_versions_all_local_assets():
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    html = response.text
    for asset in (
        "style.css", "api.js", "chat-state.js", "navigation-state.js",
        "tweaks-panel.jsx", "mascot.jsx", "components.jsx", "edit.jsx",
        "pages.jsx", "main.jsx",
    ):
        assert f'/{asset}?v=20260807-conversation-attention' in html


def test_frontend_scripts_are_revalidated():
    response = TestClient(app).get("/pages.jsx?v=20260807-conversation-attention")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, must-revalidate"
    assert "function PlanningBriefCard" in response.text
    assert "memory.applied_facts" in response.text
