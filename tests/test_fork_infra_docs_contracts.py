# -*- coding: utf-8 -*-
"""fork：CI 映像守門、PR 範本基準、台股文件與程式一致性的契約。

刻意不改上游的 test_ci_workflow_contract.py（同步上游時會衝突），只借用它的過濾器模型。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_ci_workflow_contract import _expand_brace_pattern, _workflow

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _glob_regex(pattern: str) -> re.Pattern:
    # 照 picomatch 語意：`*` 不跨 `/`，`**` 跨目錄。上游測試用的 fnmatch 讓 `*.py`
    # 也命中 `market_data/x.py`，會把漏列的目錄判成有覆蓋。
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def _filter_output(paths: list[str], rules: list[str]) -> bool:
    def rule_ok(path: str, rule: str) -> bool:
        hit = any(_glob_regex(p).match(path) for p in _expand_brace_pattern(rule.removeprefix("!")))
        return not hit if rule.startswith("!") else hit

    return any(all(rule_ok(path, r) for r in rules) for path in paths)


def test_glob_model_matches_picomatch_semantics():
    assert _filter_output(["main.py"], ["*.py"])
    assert not _filter_output(["market_data/x.py"], ["*.py"])
    assert _filter_output(["market_data/a/b.py"], ["market_data/**"])
    assert not _filter_output(["market_data/AGENTS.md"], ["market_data/**", "!**/*.md"])


def _docker_rules() -> list[str]:
    import yaml

    ci = _workflow(".github/workflows/ci.yml")
    step = next(s for s in ci["jobs"]["changes"]["steps"] if s.get("id") == "filter")
    return yaml.load(str(step["with"]["filters"]), Loader=yaml.BaseLoader)["docker"]


def _dockerfile_copy_sources() -> list[str]:
    sources = []
    for line in _read("docker/Dockerfile").splitlines():
        parts = line.split()
        if not parts or parts[0] != "COPY" or any(p.startswith("--from") for p in parts):
            continue
        sources.extend(parts[1:-1])
    return sources


def test_docker_filter_covers_every_dockerfile_copy_source():
    rules = _docker_rules()
    sources = _dockerfile_copy_sources()
    assert "market_data/*.py" in sources and "templates/" in sources
    for src in sources:
        sample = src + "x.py" if src.endswith("/") else src.replace("*", "x")
        assert _filter_output([sample], rules), f"{sample}（COPY {src}）改了 docker-build 不會跑"


def test_docker_filter_still_skips_docs_only_changes():
    rules = _docker_rules()
    for path in ("market_data/AGENTS.md", "docs/CHANGELOG.md", "journal/media-picks.jsonl", "README.md"):
        assert not _filter_output([path], rules), path


def _backend_rules() -> list[str]:
    import yaml

    ci = _workflow(".github/workflows/ci.yml")
    step = next(s for s in ci["jobs"]["changes"]["steps"] if s.get("id") == "backend-filter")
    return yaml.load(str(step["with"]["filters"]), Loader=yaml.BaseLoader)["backend_non_web"]


def test_backend_filter_skips_journal_and_ios_only_changes():
    # 排程每天自動推 journal/*.jsonl 到 develop；不排除就每筆都跑完整 4 片後端測試。
    rules = _backend_rules()
    for path in ("journal/media-picks-verdicts.jsonl", "journal/closed-dates.txt",
                 "apps/dsa-ios/App/ContentView.swift", "apps/dsa-ios/Core/Package.swift"):
        assert not _filter_output([path], rules), path


def test_backend_filter_still_runs_for_backend_inputs_next_to_skipped_paths():
    # 反向：排除不能擴大到相鄰的程式碼（腳本、.claude 底下的程式、後端、測試）。
    rules = _backend_rules()
    for path in ("scripts/verify_swing_decisions.py", ".claude/skills/verify/scripts/instance.py",
                 "src/agent/chat_object_decision.py", "market_data/db.py", "tests/test_x.py"):
        assert _filter_output([path], rules), path


def _md_files_read_by_tests() -> dict[str, str]:
    """測試裡用 read_text／_read(／*_PATH = 讀的 repo 內 .md（相對路徑 -> 第一個出處）。"""
    found: dict[str, str] = {}
    for test_root in ("tests", "market_data/tests"):
        for path in sorted((REPO_ROOT / test_root).rglob("*.py")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if '.md"' not in line or not re.search(r"read_text|_read\(|_PATH\s*=", line):
                    continue
                segs = re.findall(r'"([A-Za-z0-9_./-]+)"', line)
                for i, seg in enumerate(segs):
                    if not seg.endswith(".md"):
                        continue
                    # 取最長且存在的路徑：`ROOT / ".claude" / ... / "SKILL.md"` 不該被當成根目錄的 SKILL.md
                    hits = ["/".join(segs[j:i + 1]) for j in range(i + 1)]
                    hit = next((h for h in hits if (REPO_ROOT / h).is_file()), None)
                    if hit:
                        found.setdefault(hit, f"{path.relative_to(REPO_ROOT)}:{n}")
    return found


def _backend_triggered(path: str) -> bool:
    import yaml

    ci = _workflow(".github/workflows/ci.yml")
    step = next(s for s in ci["jobs"]["changes"]["steps"] if s.get("id") == "filter")
    filters = yaml.load(str(step["with"]["filters"]), Loader=yaml.BaseLoader)
    return (_filter_output([path], _backend_rules())
            or _filter_output([path], filters["backend_contract_assets"])
            or _filter_output([path], filters["backend_web_contract"]))


def test_every_markdown_read_by_tests_triggers_backend():
    # `!**/*.md` 會讓「只改文件」不跑後端；被測試讀的 md 要列進 backend_contract_assets，
    # 否則只改那份文件時，讀它的契約測試永遠不會跑（踩過：PR 範本、台股文件、skill）。
    found = _md_files_read_by_tests()
    assert ".github/PULL_REQUEST_TEMPLATE.md" in found  # 掃描器本身還看得到東西
    missing = {p: src for p, src in found.items() if not _backend_triggered(p)}
    assert not missing, f"這些 md 被測試讀取，但只改它們不會跑後端：{missing}"


def test_plain_docs_still_skip_backend():
    # 反向：沒有測試讀的文件仍不該觸發後端。
    for path in ("README.md", "docs/research/2026-10-01-x.md", "docs/ci-self-hosted-runner.md",
                 ".claude/skills/portfolio-check/SKILL.md"):
        assert not _backend_triggered(path), path


def _serve_path_market_data_modules() -> set[str]:
    modules: set[str] = set()
    files = [p for d in ("src", "data_provider", "api", "bot") for p in (REPO_ROOT / d).rglob("*.py")]
    files += list(REPO_ROOT.glob("*.py"))
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module == "market_data":
                    names = [f"market_data.{a.name}" for a in node.names]
                else:
                    names = [node.module]
            else:
                continue
            modules.update(n for n in names if n.startswith("market_data."))
    return modules


def test_docker_smoke_imports_every_serve_path_market_data_module():
    steps = _workflow(".github/workflows/ci.yml")["jobs"]["docker-build"]["steps"]
    smoke = next(s for s in steps if s.get("name") == "🔍 Docker smoke imports")["run"]
    smoked = set(re.findall(r"market_data\.[a-z_]+", smoke))
    used = _serve_path_market_data_modules()
    assert used, "解析不到任何 market_data import，掃描範圍壞了"
    assert used <= smoked, f"Docker smoke 沒 import：{sorted(used - smoked)}"
    for mod in used | smoked:
        rel = mod.split(".", 1)[1]
        # Dockerfile 只 COPY market_data/*.py：子套件不會進映像
        assert "." not in rel and (REPO_ROOT / "market_data" / f"{rel}.py").is_file(), mod


def test_develop_runs_are_not_cancelled_by_later_pushes():
    concurrency = _workflow(".github/workflows/ci.yml")["concurrency"]
    assert concurrency["group"] == "ci-${{ github.event.pull_request.number || github.ref }}"
    # 工作分支仍要取消舊 run；只有 develop 例外
    assert concurrency["cancel-in-progress"] == "${{ github.ref != 'refs/heads/develop' }}"


def test_pr_template_diffs_against_develop():
    template = _read(".github/PULL_REQUEST_TEMPLATE.md")
    assert "BASE_REF=$(git merge-base HEAD origin/develop)" in template
    assert "origin/main" not in template


def test_level_alert_checklist_requires_scheduler():
    doc = _read("docs/tw-level-alerts.md")
    step = doc.split("4. **警報輪詢要開著**", 1)[1].split("\n5. ", 1)[0]
    assert "AGENT_EVENT_MONITOR_ENABLED=true" in step
    assert "SCHEDULE_ENABLED=true" in step and "--schedule" in step


def _monitor_registered(schedule_enabled: bool) -> bool:
    from src.services.runtime_scheduler import RuntimeSchedulerService

    class _FakeScheduler:
        def __init__(self, **kwargs):
            self.background = []

        def set_daily_task(self, task, run_immediately):
            pass

        def add_background_task(self, task, interval_seconds, run_immediately, name=None):
            self.background.append(name)

        def run(self):
            pass

    config = SimpleNamespace(
        schedule_enabled=schedule_enabled,
        schedule_time="18:00",
        schedule_times=["18:00"],
        agent_event_monitor_enabled=True,
        agent_event_monitor_interval_minutes=5,
    )
    service = RuntimeSchedulerService(config_provider=lambda: config, owns_schedule=True)
    service._reload_config = lambda: config
    with patch("src.services.runtime_scheduler.Scheduler", _FakeScheduler), patch(
        "src.services.alert_worker.AlertWorker"
    ), patch("src.services.runtime_scheduler.threading.Thread"):
        service.reconcile_from_config()
    scheduler = service._scheduler
    return scheduler is not None and "agent_event_monitor" in scheduler.background


def test_alert_monitor_needs_schedule_enabled_as_documented():
    # 文件第 4 步的依據：只開 AGENT_EVENT_MONITOR_ENABLED、排程器沒開時，警報輪詢不會註冊
    assert _monitor_registered(schedule_enabled=False) is False
    assert _monitor_registered(schedule_enabled=True) is True


def _shioaji_index_codes() -> set[str]:
    tree = ast.parse(_read("data_provider/shioaji_fetcher.py"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "_TW_MAIN_INDEX_CONTRACTS" for t in node.targets
        ):
            return {(e.elts[0].value, e.elts[1].value) for e in node.value.elts}
    raise AssertionError("找不到 _TW_MAIN_INDEX_CONTRACTS")


def test_realtime_board_index_contract_codes_match_fetcher():
    doc = _read("docs/realtime-board.md")
    cited = set(re.findall(r'Indexs\.(TSE|OTC)\["([^"]+)"\]', doc))
    assert cited, "文件不再提指數合約代碼，這個守門要跟著調整"
    assert cited <= _shioaji_index_codes(), f"文件寫的合約代碼和程式不一致：{sorted(cited)}"


def test_upstream_sync_skill_does_not_cite_agents_as_forbidding_develop_merge():
    skill = _read(".claude/skills/dsa-upstream-sync/SKILL.md")
    assert "永遠留給使用者（repo `AGENTS.md` §1、§9）" not in skill
    assert "§1、§9 允許 agent 在 CI 綠後自己合進 `develop`" in skill
    assert "由使用者審過後決定（§9）" not in skill
