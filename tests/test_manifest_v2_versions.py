"""清单与插件 __plugin__ 的 version 必须一致，否则商店永不推更新（AGENTS.md 规则）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins_v2.juai_checkin import __plugin__

ROOT = Path(__file__).resolve().parents[1]


def _manifest_version(plugin_id: str) -> str:
    manifest = json.loads((ROOT / "manifest_v2.json").read_text(encoding="utf-8"))
    return manifest["plugins"][plugin_id]["version"]


def test_v2_metadata_keeps_schema_configuration() -> None:
    assert __plugin__["version"] == _manifest_version("juai_checkin")
    assert __plugin__["plugin_api_version"] == 2
    assert __plugin__["resources"]["max_background_tasks"] == 8
    assert __plugin__["scope"] == "standalone"
    assert "render_mode" not in __plugin__
    assert __plugin__["requirements"] == ["httpx>=0.27", "beautifulsoup4>=4.12"]
    assert __plugin__["config_schema"]["accounts"]["fields"]["password"]["type"] == "password"


def test_manifest_v2_versions_match_plugin_meta() -> None:
    """所有 V2 插件：清单版本 == __plugin__.version（商店按清单版本判定更新）。"""
    manifest = json.loads((ROOT / "manifest_v2.json").read_text(encoding="utf-8"))
    for plugin_id, entry in manifest["plugins"].items():
        module = pytest.importorskip(f"plugins_v2.{plugin_id}")
        meta = getattr(module, "__plugin__", None)
        if meta is None:
            continue
        assert meta["version"] == entry["version"], f"{plugin_id} 清单与 __plugin__ 版本不一致"
        assert meta.get("id") == plugin_id
