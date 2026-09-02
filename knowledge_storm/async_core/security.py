"""Path, identity, probe-URL and TOML guards for the SuZhi HTTP surface."""

from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

_METADATA_HOSTS = {
    "metadata.google.internal",
    "metadata.goog",
    "metadata",
    "instance-data",
}

_BLOCKED_PROBE_NETWORKS = (
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fd00:ec2::/32"),  # AWS IMDSv2 IPv6
)


class SecurityError(ValueError):
    """Raised when a caller-supplied path, id or URL is rejected."""


def validate_task_id(task_id: str) -> str:
    if not task_id or not TASK_ID_RE.fullmatch(task_id):
        raise SecurityError("非法任务编号")
    if ".." in task_id or "/" in task_id or "\\" in task_id:
        raise SecurityError("非法任务编号")
    return task_id


def safe_task_dir(root: Path, task_id: str) -> Path:
    """Resolve results_async/<task_id> and refuse path escape."""
    validate_task_id(task_id)
    base = (Path(root) / "results_async").resolve()
    target = (base / task_id).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise SecurityError("任务目录越界") from exc
    return target


def safe_local_docs_dir(root: Path, user_path: Optional[str]) -> Optional[Path]:
    """Local corpus must exist and stay under the project root."""
    if not user_path or not str(user_path).strip():
        return None
    raw = Path(str(user_path).strip())
    root_r = Path(root).resolve()
    candidate = raw.resolve() if raw.is_absolute() else (root_r / raw).resolve()
    try:
        candidate.relative_to(root_r)
    except ValueError as exc:
        raise SecurityError("本地语料路径必须位于工程目录内") from exc
    if not candidate.is_dir():
        raise SecurityError("本地语料路径不存在或不是目录")
    return candidate


def toml_quote(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _host_is_blocked(hostname: str) -> bool:
    host = (hostname or "").strip("[]").lower().rstrip(".")
    if host in _METADATA_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.is_link_local or ip.is_unspecified or ip.is_multicast:
        return True
    for net in _BLOCKED_PROBE_NETWORKS:
        if ip in net:
            return True
    return False


def assert_probe_url_safe(url: str) -> str:
    """Allow http(s) probes; block file/gopher and cloud-metadata endpoints.

    Loopback and RFC1918 remain allowed so local Ollama / SearXNG still work
    when the console is bound to 127.0.0.1.
    """
    raw = (url or "").strip()
    if not raw or len(raw) > 2048:
        raise SecurityError("探测地址无效")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise SecurityError("探测仅允许 http/https")
    if parsed.username or parsed.password:
        raise SecurityError("探测地址不得包含用户名")
    host = parsed.hostname or ""
    if not host:
        raise SecurityError("探测地址缺少主机名")
    if _host_is_blocked(host):
        raise SecurityError("拒绝探测链路本地或云元数据地址")
    return raw


def pop_secrets(config_dump: dict) -> dict:
    """Strip plaintext keys from a model_dump() copy; keep masked flags."""
    for group_name in ("llm_providers", "search_providers"):
        group = config_dump.get(group_name) or {}
        for _pid, info in group.items():
            if not isinstance(info, dict):
                continue
            raw_key = info.pop("api_key", "") or ""
            info["has_key"] = bool(raw_key)
            if raw_key and len(raw_key) > 8:
                info["api_key_masked"] = f"{raw_key[:4]}****{raw_key[-4:]}"
            else:
                info["api_key_masked"] = "未设置" if not raw_key else "****"
    return config_dump


def expected_api_token() -> str:
    return os.environ.get("SUZHI_API_TOKEN", "").strip()
