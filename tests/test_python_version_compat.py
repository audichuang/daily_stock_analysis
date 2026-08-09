# -*- coding: utf-8 -*-
"""本機（3.12）看不到、CI（3.11）才會炸的語法差異。

踩過：`scripts/screen_tw.py` 用了同引號的巢狀 f-string（PEP 701），在 3.12 完全
合法，在 3.11 是 `SyntaxError: f-string: unterminated string`。它在 `main` 上
躺著沒被發現，因為三件事剛好疊在一起：

- `.github/workflows/ci.yml` 跑 **3.11**
- 本機 venv 是 **3.12**（AGENTS.md §10：`uv venv --python 3.12`）
- CI 只在「對 main 開 PR」時觸發，而這個 fork 平常直接 push main

所以本機全綠、CI 從來沒跑過，錯誤就一直在。這個測試在**本機**就把 CI 的
Python 版本抓出來，逐檔用那個版本剖析。
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_SKIP_PARTS = (".venv", "node_modules", ".git", "site-packages", "build", "dist")


def _ci_python_versions() -> list[str]:
    """CI 實際使用的**每一個** Python 版本，直接從 workflow 讀，不寫死。

    目前 ci.yml 同時有 3.11（backend-tests / ai-governance）與 3.12（desktop 打包），
    所以原始碼必須在兩個版本下都剖析得動——只驗一個就會漏掉另一個。
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    versions = sorted(set(re.findall(r"python-version:\s*['\"]([\d.]+)['\"]", workflow)))
    assert versions, "ci.yml 沒有 python-version，這個測試的前提消失了"
    return versions


def _project_python_files() -> list[Path]:
    return [
        path for path in REPO_ROOT.rglob("*.py")
        if not any(part in _SKIP_PARTS for part in path.parts)
    ]


@pytest.mark.parametrize("ci_version", _ci_python_versions())
def test_every_source_file_parses_under_the_ci_python(ci_version: str) -> None:
    files = _project_python_files()
    assert files, "沒收集到任何 .py，收集邏輯壞了"

    if sys.version_info[:2] == tuple(int(x) for x in ci_version.split(".")[:2]):
        offenders = []
        for path in files:
            try:
                ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
            except SyntaxError as exc:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{exc.lineno} {exc.msg}")
        assert not offenders, "\n".join(offenders)
        return

    # 本機跑在別的版本上：借 uv 拉 CI 那個版本來剖析。拉不到就跳過而不是假裝通過。
    if shutil.which("uv") is None:
        pytest.skip(f"需要 uv 才能用 Python {ci_version} 驗，且目前直譯器是 {sys.version_info[:2]}")

    probe = (
        "import ast,pathlib,sys\n"
        f"skip={_SKIP_PARTS!r}\n"
        "bad=[]\n"
        f"root=pathlib.Path({str(REPO_ROOT)!r})\n"
        "for p in root.rglob('*.py'):\n"
        "    if any(s in p.parts for s in skip): continue\n"
        "    try: ast.parse(p.read_text(encoding='utf-8',errors='replace'), filename=str(p))\n"
        "    except SyntaxError as e: bad.append(f'{p.relative_to(root)}:{e.lineno} {e.msg}')\n"
        "print('\\n'.join(bad))\n"
    )
    result = subprocess.run(
        ["uv", "run", "--python", ci_version, "--no-project", "python", "-c", probe],
        capture_output=True, text=True, timeout=600, cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        pytest.skip(f"取不到 Python {ci_version}：{result.stderr.strip()[:200]}")
    offenders = result.stdout.strip()
    assert not offenders, f"這些檔案在 CI 的 Python {ci_version} 下剖析失敗：\n{offenders}"
