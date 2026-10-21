# -*- coding: utf-8 -*-
"""import src 之後再 import litellm，不能把 cwd 的 .env 補進程序環境。

踩過：臨時腳本 unset 了 STORAGE_DATABASE_URL，`api.app` → `src.analyzer` → `import litellm`
又從 repo 的 .env 把正式應用庫 URL 補回來，測試資料寫進正式庫。用子程序跑，才是乾淨的 import。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SENTINEL = "DSA_DOTENV_GUARD_SENTINEL"


def _run(tmp_path: Path, extra_env: dict[str, str]) -> str:
    (tmp_path / ".env").write_text(f"{SENTINEL}=leaked\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in (SENTINEL, "LITELLM_MODE")}
    env.update({"PYTHONPATH": str(REPO), "LITELLM_LOCAL_MODEL_COST_MAP": "True", **extra_env})
    code = f"import os, src, litellm; print(os.environ.get({SENTINEL!r}, 'unset'))"
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=120, check=True)
    return out.stdout.strip().splitlines()[-1]


def test_importing_litellm_after_src_does_not_load_cwd_dotenv(tmp_path):
    assert _run(tmp_path, {}) == "unset"


def test_explicit_litellm_mode_is_respected(tmp_path):
    # 反向：使用者明確要 DEV 時照舊載入，證明守門只是預設值、而且這支測試真的會偵測到外洩
    assert _run(tmp_path, {"LITELLM_MODE": "DEV"}) == "leaked"
