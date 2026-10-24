"""`scripts/audit_market_vs_official.py` 的純函式守門：數值解析與彙總的結束碼。"""

import json
from decimal import Decimal

from scripts.audit_market_vs_official import num, summarize


def test_num_parses_official_cells():
    assert num("1,234,567") == Decimal("1234567")
    assert num("-0.50") == Decimal("-0.50")
    assert num("<p style= color:red>+</p>") is None
    for blank in ("", "--", "----", "N/A"):
        assert num(blank) is None


def _write(tmp_path, rows):
    (tmp_path / "result.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_summary_exit_code_follows_latest_record_per_day(tmp_path, capsys):
    bad = {"date": "2026-07-28", "source": "t86", "err": None, "miss": 5, "extra": 0, "bad": 33}
    fixed = dict(bad, miss=0, bad=0)
    _write(tmp_path, [bad])
    assert summarize(tmp_path) == 1
    assert "2026-07-28" in capsys.readouterr().out
    # A re-run after the repair appends a clean record; the latest one wins
    _write(tmp_path, [bad, fixed])
    assert summarize(tmp_path) == 0


def test_summary_flags_unreadable_days(tmp_path):
    _write(tmp_path, [{"date": "2012-01-02", "source": "t86", "err": "stat mismatch"}])
    assert summarize(tmp_path) == 1
