# -*- coding: utf-8 -*-
"""scripts/portfolio_codes.py：持倉快照 → 台股代號清單。全用假 snapshot，不連 DB（conftest 已清空 STORAGE_DATABASE_URL）。"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("portfolio_codes", ROOT / "scripts" / "portfolio_codes.py")
pc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)


def _pos(symbol, qty=1000, market="tw", name="某股"):
    return {"symbol": symbol, "name": name, "market": market, "quantity": qty}


def _snap(*accounts):
    return {"as_of": "2026-10-26", "accounts": list(accounts)}


def _acc(name, *positions, market="tw"):
    return {"account_id": 1, "account_name": name, "market": market, "positions": list(positions)}


def test_collect_filters_zero_quantity_and_non_tw():
    out = pc.collect(_snap(
        _acc("國泰", _pos("2330.TW", 1000), _pos("6191.TW", 0), _pos("3481.TW", -5)),
        _acc("永豐", _pos("AAPL", 10, market="us"), market="us"),
    ))
    assert [c["code"] for c in out["codes"]] == ["2330.TW"]
    assert out["as_of"] == "2026-10-26"
    assert out["skipped"] == []                        # 美股是被市場過濾掉的，不是「對不到代號」


def test_collect_merges_accounts_and_sums_quantity():
    out = pc.collect(_snap(_acc("美好", _pos("2330.TW", 1000)), _acc("國泰", _pos("2330.TW", 500))))
    (row,) = out["codes"]
    assert row["accounts"] == ["美好", "國泰"] and row["quantity"] == 1500


def test_collect_keeps_letter_suffix_and_tpex_codes():
    out = pc.collect(_snap(_acc("a", _pos("00631l.tw"), _pos("2887A.TW"), _pos("6488.TWO"))))
    assert [c["code"] for c in out["codes"]] == ["00631L.TW", "2887A.TW", "6488.TWO"]


def test_collect_normalises_bare_codes_via_index_and_reports_unresolvable(tmp_path):
    index = tmp_path / "stocks.index.json"
    index.write_text(json.dumps([["2330.TW", "2330", "台積電"], ["6488.TWO", "6488", "環球晶"],
                                 ["00631L.TW", "00631L", "正2"], ["AAPL", "AAPL", "Apple"]]), encoding="utf-8")
    out = pc.collect(_snap(_acc("a", _pos("2330"), _pos("6488"), _pos("00631L"), _pos("9999"), _pos("ABC"))), index)
    assert [c["code"] for c in out["codes"]] == ["00631L.TW", "2330.TW", "6488.TWO"]
    assert out["skipped"] == ["9999", "ABC"]          # 對不到後綴的不猜，列在 skipped


def test_collect_drops_malformed_suffix_codes():
    out = pc.collect(_snap(_acc("a", _pos("2330甲.TW"), _pos("12.TW"), _pos("7203.T"))))
    assert out["codes"] == [] and len(out["skipped"]) == 3


def test_main_prints_json_and_exit_0(capsys):
    rc = pc.main([], snapshot_fn=lambda: _snap(_acc("a", _pos("2330.TW"))))
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["codes"][0]["code"] == "2330.TW"


def test_main_error_prints_json_error_without_leaking_message(capsys):
    def boom():
        raise RuntimeError("could not connect postgresql://user:secret@host/db")

    rc = pc.main([], snapshot_fn=boom)
    out = capsys.readouterr().out
    assert rc == 1
    assert list(json.loads(out)) == ["error"]
    assert "secret" not in out and "postgresql" not in out


def test_default_snapshot_uses_read_only_service(monkeypatch):
    calls = {}

    class Fake:
        def get_portfolio_snapshot(self, **kw):
            calls.update(kw)
            return _snap()

    import src.services.portfolio_service as ps
    monkeypatch.setattr(ps, "PortfolioService", Fake)
    pc._snapshot()
    assert calls == {"include_realtime": False, "read_only": True}
