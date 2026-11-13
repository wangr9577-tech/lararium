"""Verify paper AI routes are registered and require a local session."""
from backend.tests.test_env import TestEnvironment


def test_paper_ai_routes_registered_and_authenticated():
    env = TestEnvironment(prefix="kruskal_paper_ai_routes_")
    env.setup()
    try:
        for endpoint in ("paper-question", "paper-summary", "paper-explain"):
            url = f"/api/ai/{endpoint}"
            assert env.client.post(url, json={}).status_code == 401
            # An authenticated request with a missing body must reach the
            # registered endpoint's validation, not the SPA fallback.
            assert env.client.post(url, json={}, headers=env.auth_headers()).status_code == 422
    finally:
        env.teardown()
