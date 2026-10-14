# -*- coding: utf-8 -*-
"""台股代号格式的契约：凡是写了「数字位数 + TW」的正则，都要允许一个尾字母。

台股代号是 4~6 位数字加至多一个大写字母（00631L / 00632R / 00679B / 2887A），但这条
格式在前后端、报告渲染、索引脚本里各有一份正则，没有共用来源。只认纯数字的那份会让
带字母的代号静默消失（自动补全搜不到、分享图把 00631L.TW 截成 00631），不会报错。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_ROOTS = ["main.py", "server.py", "src", "api", "data_provider", "bot", "scripts", "market_data", "apps/dsa-web/src"]
SUFFIXES = {".py", ".ts", ".tsx"}
SKIP_PARTS = {"__tests__", "node_modules", "__pycache__"}

DIGIT_COUNT = re.compile(r"(\\d|\[0-9\])\{\d+(,\d*)?\}")
TW_TOKEN = re.compile(r"\bTWO?\b")
LETTER = "[A-Z]"

# 同一个正则里台股分支已在上一行单独处理（带尾字母），这一行只是其他市场的通用分支。
ALLOWED = {
    ("src/agent/stock_scope.py", r"\d{1,6}\.(?:SH|SZ|SS|BJ|HK|KS|KQ|TW|T|CSI)"),
}


def _source_files(root):
    for name in SCAN_ROOTS:
        path = root / name
        files = [path] if path.is_file() else path.rglob("*")
        for p in files:
            if p.suffix in SUFFIXES and not SKIP_PARTS.intersection(p.parts):
                yield p


def find_digit_only_tw_patterns(root=ROOT):
    hits = []
    for path in _source_files(root):
        rel = path.relative_to(root).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if not (DIGIT_COUNT.search(line) and TW_TOKEN.search(line)) or LETTER in line:
                continue
            if any(rel == f and snippet in line for f, snippet in ALLOWED):
                continue
            hits.append(f"{rel}:{lineno}: {line.strip()}")
    return hits


def test_tw_code_patterns_allow_one_trailing_letter():
    hits = find_digit_only_tw_patterns()
    assert not hits, (
        "这些正则把台股代号限定为纯数字，00631L.TW / 2887A.TW 会被漏掉；"
        "补上 [A-Z]?，或确认台股分支已另行处理后加进 ALLOWED：\n" + "\n".join(hits)
    )


def test_scanner_catches_a_digit_only_tw_pattern(tmp_path):
    # 反向守门：扫描器本身要能抓到旧写法，否则上面那支永远是绿的。
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "bad.py").write_text('RE = r"\\d{4,6}\\.(?:TWO|TW)"\n', encoding="utf-8")
    (tmp_path / "src" / "good.py").write_text('RE = r"\\d{4,6}[A-Z]?\\.(?:TWO|TW)"\n', encoding="utf-8")
    assert find_digit_only_tw_patterns(tmp_path) == ['src/bad.py:1: RE = r"\\d{4,6}\\.(?:TWO|TW)"']
