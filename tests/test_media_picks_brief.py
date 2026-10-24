# -*- coding: utf-8 -*-
"""scripts/media_picks_brief.py：最近一輪判斷選取、過期邊界、持股優先、各區塊、持股取不到、缺 journal。不連 DB。"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("media_picks_brief", ROOT / "scripts" / "media_picks_brief.py")
mb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mb)


def _v(date, code, verdict, name=None, thesis="論點", flip="翻轉條件"):
    return {"date": date, "code": code, "name": name or f"名{code[:4]}", "verdict": verdict,
            "thesis": thesis, "flip": flip}


def _run(tmp_path, capsys, rows, *extra, holdings=None, holdings_fn=None):
    (tmp_path / "media-picks-verdicts.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    args = ["--journal-dir", str(tmp_path), *extra]
    if holdings is not None:
        h = tmp_path / "h.json"
        h.write_text(json.dumps(holdings), encoding="utf-8")
        args += ["--holdings", str(h)]
    assert mb.main(args, holdings_fn=holdings_fn) == 0
    return capsys.readouterr().out


def _held(*codes):
    return {"codes": [{"code": c} for c in codes]}


def test_latest_date_and_last_row_wins(tmp_path, capsys):
    out = _run(tmp_path, capsys, [
        _v("2026-10-23", "1111.TW", "research", "舊輪"),
        _v("2026-10-25", "2222.TW", "watch", "乙", flip="第一版"),
        _v("2026-10-25", "2222.TW", "research", "乙", thesis="第二版"),
    ], "--today", "2026-10-26", holdings=_held())
    assert "2026-10-25" in out and "舊輪" not in out
    assert "第二版" in out and "第一版" not in out
    assert "【research】" in out and "【watch" not in out


def test_stale_boundary(tmp_path, capsys):
    rows = [_v("2026-10-20", "2222.TW", "research")]
    ok = _run(tmp_path, capsys, rows, "--today", "2026-10-24", holdings=_held())  # 剛好 4 天
    assert "已過期" not in ok and "最近一輪媒體點名" in ok
    stale = _run(tmp_path, capsys, rows, "--today", "2026-10-25", holdings=_held())  # 5 天
    assert stale.strip() == "（最近一輪媒體點名判斷是 2026-10-20，已過期）"


def test_held_avoid_listed_first(tmp_path, capsys):
    out = _run(tmp_path, capsys, [
        _v("2026-10-25", "3333.TW", "watch", "丙"),
        _v("2026-10-25", "4444.TW", "research", "丁"),
        _v("2026-10-25", "5555.TW", "avoid", "戊"),
    ], "--today", "2026-10-26", holdings=_held("3333.TW", "4444.TW", "5555.TW"))
    block = out.split("【持股相關】")[1]
    assert block.index("戊") < block.index("丁") < block.index("丙")
    assert "【research】" not in out and "避開：" not in out  # 已在持股相關列過，不重複


def test_sections(tmp_path, capsys):
    out = _run(tmp_path, capsys, [
        _v("2026-10-25", "1000.TW", "research", "甲", thesis="甲論點", flip="甲翻轉"),
        _v("2026-10-25", "2000.TW", "watch", "乙", thesis="乙論點", flip="乙翻轉"),
        _v("2026-10-25", "3000.TW", "avoid", "丙"),
        _v("2026-10-25", "4000.TW", "avoid", "丁"),
        _v("2026-10-25", "5000.TW", "watch", "戊", flip="戊翻轉"),
    ], "--today", "2026-10-26", holdings=_held("5000.TW"))
    assert "===== 最近一輪媒體點名（2026-10-25，僅供參考，不是買進訊號）=====" in out
    assert "【持股相關】\n- 戊 5000.TW｜watch" in out
    research = out.split("【research】")[1].split("【")[0]
    assert "甲論點" in research and "甲翻轉" in research
    watch = out.split("【watch 的翻轉條件】")[1]
    assert "乙翻轉" in watch and "乙論點" not in watch and "戊" not in watch
    assert "避開：丙、丁" in out


def test_truncation(tmp_path, capsys):
    out = _run(tmp_path, capsys, [_v("2026-10-25", "1000.TW", "research", thesis="字" * 100, flip="翻" * 100)],
               "--today", "2026-10-26", holdings=_held())
    assert "字" * 60 + "…" in out and "字" * 61 not in out
    assert "翻" * 80 + "…" in out and "翻" * 81 not in out


def test_holdings_failure_continues(tmp_path, capsys):
    rows = [_v("2026-10-25", "1000.TW", "research", "甲")]
    out = _run(tmp_path, capsys, rows, "--today", "2026-10-26", holdings_fn=lambda: None)
    assert "持股清單取不到" in out and "【research】" in out and "【持股相關】" not in out
    ok = _run(tmp_path, capsys, rows, "--today", "2026-10-26", holdings=_held())
    assert "持股清單取不到" not in ok
    # 壞的 --holdings 檔、含 error 的檔也算取不到
    bad = _run(tmp_path, capsys, rows, "--today", "2026-10-26", holdings={"error": "x", "codes": [{"code": "1000.TW"}]})
    assert "持股清單取不到" in bad and "【持股相關】" not in bad


def test_missing_journal(tmp_path, capsys):
    assert mb.main(["--journal-dir", str(tmp_path), "--today", "2026-10-26"],
                   holdings_fn=lambda: (_ for _ in ()).throw(AssertionError("不該查持股"))) == 0
    assert capsys.readouterr().out.strip() == "沒有媒體點名判斷"


def test_json_output(tmp_path, capsys):
    out = _run(tmp_path, capsys, [_v("2026-10-25", "1000.TW", "avoid", "甲")], "--today", "2026-10-26", "--json",
               holdings=_held("1000.TW"))
    d = json.loads(out)
    assert d["status"] == "ok" and d["held"][0]["code"] == "1000.TW"


def test_malformed_date_rows_are_skipped_not_crash(tmp_path, capsys):
    rows = [_v("2026-10-25", "2222.TW", "research", "乙"),
            _v("not-a-date", "3333.TW", "research", "丙"),          # 字串排序比 2026-... 大：沒濾掉會被當成最近一輪
            _v("2026-13-45", "4444.TW", "research", "丁"),
            {"date": 20261025, "code": "5555.TW", "verdict": "research"},
            {"date": None, "code": "6666.TW", "verdict": "research"}]
    out = _run(tmp_path, capsys, rows, "--today", "2026-10-26", holdings=_held())
    assert "2026-10-25" in out and "乙" in out
    assert "丙" not in out and "丁" not in out and "5555" not in out
