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


def test_default_snapshot_uses_read_only_engine_and_disposes(monkeypatch):
    seen = {}

    class FakeEngine:
        def dispose(self):
            seen["disposed"] = True

    monkeypatch.setenv("STORAGE_DATABASE_URL", "sqlite://")
    monkeypatch.setattr(pc, "_read_only_engine", lambda url: seen.update(url=url) or FakeEngine())
    monkeypatch.setattr(pc, "_load_snapshot", lambda engine: seen.update(engine=engine) or _snap())
    assert pc._snapshot() == _snap()
    assert seen["url"] == "sqlite://" and isinstance(seen["engine"], FakeEngine) and seen["disposed"]


# ---- 讀路徑：不能碰 PortfolioService／DatabaseManager（它的 __init__ 會對正式應用庫寫入），只 SELECT ----

def test_module_never_references_service_or_database_manager_or_create_all():
    import ast
    tree = ast.parse((ROOT / "scripts" / "portfolio_codes.py").read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree)
                                                                          if isinstance(n, ast.Attribute)}
    imported = {a.name.split(".")[-1] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in n.names} | {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    banned = {"PortfolioService", "DatabaseManager", "create_all", "portfolio_service", "PortfolioRepository",
              "src.storage", "src.repositories.portfolio_repo", "get_db"}
    assert not (names | imported) & banned, (names | imported) & banned


def test_load_snapshot_runs_without_importing_service_modules(tmp_path):
    """子行程：讀一個 SQLite 庫後，service／storage 模組都不能出現在 sys.modules。"""
    import subprocess
    import sys
    code = (
        "import sys, importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('pc', {str(ROOT / 'scripts' / 'portfolio_codes.py')!r})\n"
        "pc = importlib.util.module_from_spec(spec); spec.loader.exec_module(pc)\n"
        "from sqlalchemy import create_engine\n"
        "e = create_engine('sqlite://')\n"
        "from sqlalchemy import text\n"
        "with e.begin() as c:\n"
        "    c.execute(text('create table portfolio_accounts (id integer, name text, market text, is_active boolean)'))\n"
        "    c.execute(text('create table portfolio_trades (id integer, account_id integer, trade_date date, symbol text,"
        " market text, currency text, side text, quantity float, price float)'))\n"
        "    c.execute(text('create table portfolio_corporate_actions (id integer, account_id integer, effective_date date,"
        " symbol text, market text, currency text, action_type text, split_ratio float)'))\n"
        "pc._load_snapshot(e)\n"
        "bad = [m for m in ('src.services.portfolio_service', 'src.storage', 'src.repositories.portfolio_repo')"
        " if m in sys.modules]\n"
        "print('BAD', bad)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120,
                         env={**__import__("os").environ, "STORAGE_DATABASE_URL": ""})
    assert out.returncode == 0, out.stderr[-500:]
    assert "BAD []" in out.stdout


def _seeded_engine(tmp_path):
    """用真實 model 的 portfolio 表（只在測試裡建 schema）建 SQLite 庫。"""
    from sqlalchemy import create_engine
    from src.storage import (Base, PortfolioAccount, PortfolioCorporateAction, PortfolioTrade)
    e = create_engine(f"sqlite:///{tmp_path / 'p.db'}")
    Base.metadata.create_all(e, tables=[t.__table__ for t in (PortfolioAccount, PortfolioTrade, PortfolioCorporateAction)])
    return e


def _insert(engine, table_cls, **kw):
    from sqlalchemy.orm import Session
    with Session(engine) as s:
        s.add(table_cls(**kw))
        s.commit()


def test_load_snapshot_replays_quantities_from_real_tables(tmp_path):
    import datetime as dt
    from src.storage import PortfolioAccount, PortfolioCorporateAction, PortfolioTrade
    e = _seeded_engine(tmp_path)
    d = dt.date
    _insert(e, PortfolioAccount, id=1, name="國泰", market="tw", base_currency="TWD", is_active=True)
    _insert(e, PortfolioAccount, id=2, name="永豐", market="us", base_currency="USD", is_active=True)
    _insert(e, PortfolioAccount, id=3, name="停用", market="tw", base_currency="TWD", is_active=False)
    n = iter(range(1, 100))

    def trade(acc, sym, side, qty, day, market="tw", cur="TWD"):
        _insert(e, PortfolioTrade, id=next(n), account_id=acc, symbol=sym, market=market, currency=cur,
                trade_date=day, side=side, quantity=qty, price=10.0)
    trade(1, "2330.TW", "buy", 1000, d(2026, 1, 5))
    trade(1, "2330.TW", "buy", 500, d(2026, 2, 5))
    trade(1, "2330.TW", "sell", 300, d(2026, 3, 5))              # 1200
    trade(1, "6191.TW", "buy", 1000, d(2026, 1, 5))
    trade(1, "6191.TW", "sell", 1000, d(2026, 2, 5))             # 清倉 → 不列
    trade(1, "00631L.TW", "buy", 100, d(2026, 1, 5))
    _insert(e, PortfolioCorporateAction, id=1, account_id=1, symbol="00631L.TW", market="tw", currency="TWD",
            effective_date=d(2026, 2, 1), action_type="split_adjustment", split_ratio=2.0)   # 100 → 200
    _insert(e, PortfolioCorporateAction, id=2, account_id=1, symbol="2330.TW", market="tw", currency="TWD",
            effective_date=d(2026, 2, 1), action_type="cash_dividend", split_ratio=None)     # 股利不改數量
    trade(2, "AAPL", "buy", 10, d(2026, 1, 5), market="us", cur="USD")                       # 非台股
    trade(3, "2454.TW", "buy", 1000, d(2026, 1, 5))                                          # 停用帳戶
    trade(1, "3481.TW", "buy", 700, d(2099, 1, 1))                                           # 未來成交：as_of 之後不算

    snap = pc._load_snapshot(e, as_of=d(2026, 10, 25))
    assert snap["as_of"] == "2026-10-25" and [a["account_name"] for a in snap["accounts"]] == ["國泰", "永豐"]
    out = pc.collect(snap)
    assert {c["code"]: c["quantity"] for c in out["codes"]} == {"00631L.TW": 200.0, "2330.TW": 1200.0}
    assert out["skipped"] == []
    assert out["codes"][0]["accounts"] == ["國泰"]
    held = {p["symbol"]: p["quantity"] for p in snap["accounts"][0]["positions"]}
    assert held == {"00631L.TW": 200.0, "2330.TW": 1200.0}        # 已清倉的 6191 不在 snapshot（不只是被 collect 濾掉）


def test_replay_oversell_raises_and_main_hides_url(monkeypatch, capsys):
    import datetime as dt
    import types
    t = lambda i, side, qty: types.SimpleNamespace(id=i, trade_date=dt.date(2026, 1, i), symbol="2330.TW", market="tw",  # noqa: E731
                                                   currency="TWD", side=side, quantity=qty, price=1.0)
    import pytest
    with pytest.raises(ValueError):
        pc._replay_quantities([t(1, "buy", 100), t(2, "sell", 101)], [])
    assert pc._replay_quantities([t(1, "buy", 100), t(2, "sell", 100)], []) == {("2330.TW", "tw", "TWD"): 0.0}

    monkeypatch.setenv("STORAGE_DATABASE_URL", "postgresql://u:secretpw@nohost.invalid:1/db")
    monkeypatch.setattr(pc, "_load_snapshot", lambda engine, as_of=None: (_ for _ in ()).throw(RuntimeError("secretpw")))
    assert pc.main([]) == 1
    out = capsys.readouterr().out
    assert "error" in out and "secretpw" not in out and "nohost" not in out


def test_read_only_engine_keeps_search_path_and_adds_read_only_option(monkeypatch):
    import sqlalchemy
    got = []
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda url, *a, **k: got.append(url) or object())  # 不需要 driver
    pc._read_only_engine("postgresql+psycopg2://u:p@h:5/db?options=-csearch_path%3Ddsa")
    pc._read_only_engine("sqlite://")
    opts = got[0].query["options"]
    assert "search_path=dsa" in opts and "default_transaction_read_only=on" in opts   # 不能用 connect_args 蓋掉 search_path
    assert "options" not in got[1].query


def test_missing_url_is_an_error_not_a_default_database(monkeypatch, capsys):
    monkeypatch.setenv("STORAGE_DATABASE_URL", "")
    assert pc.main([]) == 1 and "error" in capsys.readouterr().out
