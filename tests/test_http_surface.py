"""HTTP 表面自动化：空主题、路径穿越、脱敏、品牌页、探测拦截。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from server.app import app

client = TestClient(app)


def test_index_branded_no_cdn():
    r = client.get("/")
    assert r.status_code == 200
    assert "溯知" in r.text
    assert "研讨现场" in r.text
    assert "cdn.jsdelivr" not in r.text
    assert "/static/vendor/marked.min.js" in r.text


def test_vendor_marked_served():
    r = client.get("/static/vendor/marked.min.js")
    assert r.status_code == 200
    assert "marked" in r.text.lower()


def test_empty_topic_rejected():
    r = client.post("/api/v1/research/start", json={"topic": "x"})
    assert r.status_code == 422


def test_local_docs_escape():
    r = client.post(
        "/api/v1/research/start",
        json={"topic": "合法课题名称", "local_docs_dir": "/etc"},
    )
    assert r.status_code == 400
    assert "工程目录" in r.json()["detail"]


def test_task_id_traversal():
    r = client.get("/api/v1/research/article/../etc")
    assert r.status_code in (400, 404)


def test_probe_metadata_blocked():
    r = client.post(
        "/api/v1/config/probe",
        json={"type": "llm", "base_url": "http://169.254.169.254/"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "BLOCKED"


def test_providers_strip_api_key():
    r = client.get("/api/v1/config/providers")
    assert r.status_code == 200
    data = r.json()
    for info in data.get("llm_providers", {}).values():
        assert "api_key" not in info
        assert "has_key" in info


def test_knowledge_list():
    r = client.get("/api/v1/knowledge")
    assert r.status_code == 200
    assert "articles" in r.json()


def test_compare_missing():
    r = client.get("/api/v1/research/compare?left=storm_aaaaaaaa&right=storm_bbbbbbbb")
    assert r.status_code == 404


def main():
    test_index_branded_no_cdn()
    test_vendor_marked_served()
    test_empty_topic_rejected()
    test_local_docs_escape()
    test_task_id_traversal()
    test_probe_metadata_blocked()
    test_providers_strip_api_key()
    test_knowledge_list()
    test_compare_missing()
    print("ALL HTTP SURFACE TESTS PASSED")


if __name__ == "__main__":
    main()
