# -*- coding: utf-8 -*-
"""根 AGENTS.md 不放客戶端細節，AGENTS.md 指向的文件與腳本要存在。"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_ai_assets", ROOT / "scripts" / "check_ai_assets.py")
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


def test_root_rejects_client_details():
    for line in ("跑 `xcodebuild`", "改 iOS 要測", "`apps/dsa-web/` 跑 npm run lint", "先跑 vitest"):
        assert assets.root_layering_violations(line) == [line]


def test_root_allows_words_that_only_contain_client_terms():
    for line in ("period 與 scenarios 都要寫", "`.env` 的 STORAGE_DATABASE_URL", "Web 服务正式跑在 NAS"):
        assert assets.root_layering_violations(line) == []


def test_broken_pointer_is_reported_and_tracked_pointer_is_not():
    text = "见 `docs/a.md` 与 `docs/gone.md`，跑 `scripts/b.py`"
    assert assets.broken_pointers(text, {"docs/a.md", "scripts/b.py"}) == ["docs/gone.md"]


def test_paths_outside_docs_and_scripts_are_not_checked():
    assert assets.broken_pointers("`reports/x.md`、`scripts/<name>.py`", set()) == []


def test_pointer_may_be_relative_to_the_agents_file_directory():
    tracked = {"apps/x/scripts/t.sh"}
    assert assets.broken_pointers("`scripts/t.sh`", tracked, "apps/x") == []
    assert assets.broken_pointers("`scripts/t.sh`", tracked, "apps/y") == ["scripts/t.sh"]
