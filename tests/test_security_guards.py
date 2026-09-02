import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from knowledge_storm.async_core.security import (
    SecurityError,
    assert_probe_url_safe,
    pop_secrets,
    safe_local_docs_dir,
    safe_task_dir,
    toml_quote,
    validate_task_id,
)
from knowledge_storm.async_core.config_hub import ConfigHub


def test_task_id_and_dir():
    root = Path(tempfile.mkdtemp())
    (root / "results_async").mkdir()
    validate_task_id("storm_ab12cd34")
    d = safe_task_dir(root, "storm_ab12cd34")
    assert d.parent.name == "results_async"
    for bad in ("../etc", "storm/../../etc", "a/b", "..", "", "x" * 80):
        try:
            validate_task_id(bad)
            raise AssertionError(f"should reject {bad!r}")
        except SecurityError:
            pass
    try:
        safe_task_dir(root, "..")
        raise AssertionError("escape should fail")
    except SecurityError:
        pass


def test_local_docs_whitelist():
    root = Path(tempfile.mkdtemp())
    ok = root / "raw_sources"
    ok.mkdir()
    resolved = safe_local_docs_dir(root, "raw_sources")
    assert resolved == ok.resolve()
    assert safe_local_docs_dir(root, None) is None
    try:
        safe_local_docs_dir(root, "/etc")
        raise AssertionError(" /etc should fail")
    except SecurityError:
        pass
    try:
        safe_local_docs_dir(root, "../")
        raise AssertionError("parent should fail")
    except SecurityError:
        pass


def test_probe_url():
    assert_probe_url_safe("https://api.deepseek.com")
    assert_probe_url_safe("http://127.0.0.1:11434/v1")
    for bad in (
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/",
        "gopher://x",
        "http://user:pass@evil.test/",
    ):
        try:
            assert_probe_url_safe(bad)
            raise AssertionError(f"should block {bad}")
        except SecurityError:
            pass


def test_mask_strips_plaintext_key():
    hub = ConfigHub(config_path=Path(tempfile.mkstemp(suffix=".toml")[1]))
    hub.system_config.llm_providers["deepseek"].api_key = "sk-abcdefghijklmnopqrstuvwxyz"
    masked = hub.get_masked_config()
    ds = masked["llm_providers"]["deepseek"]
    assert "api_key" not in ds
    assert ds["has_key"] is True
    assert "****" in ds["api_key_masked"]
    dumped = pop_secrets({"llm_providers": {"x": {"api_key": "short"}}})
    assert "api_key" not in dumped["llm_providers"]["x"]


def test_toml_quote():
    assert toml_quote('a"b') == '"a\\"b"'


def main():
    test_task_id_and_dir()
    test_local_docs_whitelist()
    test_probe_url()
    test_mask_strips_plaintext_key()
    test_toml_quote()
    print("ALL SECURITY GUARD TESTS PASSED")


if __name__ == "__main__":
    main()
