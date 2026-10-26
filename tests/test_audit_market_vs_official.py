"""`scripts/audit_market_vs_official.py` 的純函式守門：數值解析與彙總的結束碼。"""

import json
from copy import deepcopy
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from scripts import audit_market_vs_official as audit_script
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


def test_summary_only_counts_requested_sources(tmp_path):
    _write(tmp_path, [
        {"date": "2026-07-28", "source": "t86", "err": None, "miss": 0, "extra": 0, "bad": 0},
        {"date": "2026-07-28", "source": "price", "err": None, "miss": 0, "extra": 0, "bad": 24},
    ])
    assert summarize(tmp_path, {"t86"}) == 0
    assert summarize(tmp_path, {"t86", "price"}) == 1


_SOURCES = audit_script.TWSE_SOURCES + audit_script.TPEX_SOURCES
_PREFIXES = dict(zip(("t86", "mar", "mi", "tpi", "tpm", "tpp"), _SOURCES))
_WIDTH = dict(zip(_SOURCES, (4, 6, 7, 4, 6, 7)))


def _payload(source, day):
    if source == "t86":
        fields = ["證券代號", *(names[0] for names in audit_script.T86_FIELDS)]
    elif source == "price":
        fields = ["證券代號", *audit_script.PRICE_FIELDS]
    else:
        fields = [""] * 25
        if source == "margin":
            fields[0], fields[2], fields[6], fields[12] = "代號", "買進", "今日餘額", "今日餘額"
        elif source == "tpex_margin":
            fields[3], fields[6], fields[11], fields[14] = "資買", "資餘額", "券賣", "券餘額"
    table = {"fields": fields, "data": [["2330", *(["1"] * (len(fields) - 1))]],
             "date": f"{int(day[:4]) - 1911}/{day[5:7]}/{day[8:]}"}
    return {"stat": "OK" if source in audit_script.TWSE_SOURCES else "ok",
            "date": day.replace("-", ""), "tables": [table],
            "fields": fields, "data": table["data"]}


def _cli(monkeypatch, tmp_path, sources, dates):
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.execute.return_value = [(d,) for d in dates]
    monkeypatch.setattr(audit_script, "get_engine", lambda: engine)
    monkeypatch.setattr(audit_script.sys, "argv", [
        "audit", "--out", str(tmp_path), "--sources", ",".join(sources),
        "--start", min(dates), "--end", max(dates),
    ])

    def get(self, url, name):
        prefix, ymd = name.removesuffix(".json").split("_")
        return _payload(_PREFIXES[prefix], f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}")

    monkeypatch.setattr(audit_script.Audit, "get", get)
    monkeypatch.setattr(audit_script.Audit, "db", lambda self, sql, **kw:
                        {"2330": [Decimal(1)] * (4 if "institutional" in sql else 6 if "margin" in sql else 7)})


@pytest.mark.parametrize("source", _SOURCES)
def test_main_worker_exception_fails_and_reports_incomplete_coverage(monkeypatch, tmp_path, capsys, source):
    dates = ["2026-10-23", "2026-10-22", "2026-10-21"]
    _cli(monkeypatch, tmp_path, {source}, dates)
    get = audit_script.Audit.get

    def malformed(self, url, name):
        payload = get(self, url, name)
        if "20261022" in name:
            payload["tables"][0]["data"][0][:] = ["2330"]
        return payload

    monkeypatch.setattr(audit_script.Audit, "get", malformed)
    assert audit_script.main() == 1
    output = capsys.readouterr()
    assert "worker failed" in output.err
    assert "missing 2" in output.out and "2026-10-21" in output.out and "2026-10-22" in output.out
    assert "checked 3 trading days" not in output.out
    # 失敗後離線彙總也必須保留未完成範圍，不能重新宣稱乾淨。
    assert summarize(tmp_path, {source}) == 1


@pytest.mark.parametrize("source", _SOURCES)
def test_main_complete_and_resumed_audits_still_succeed(monkeypatch, tmp_path, capsys, source):
    _cli(monkeypatch, tmp_path, {source}, ["2026-10-23", "2026-10-22"])
    assert audit_script.main() == 0
    assert "missing 0" in capsys.readouterr().out

    def no_refetch(*args, **kwargs):
        pytest.fail("已成功的日期不應重抓")

    monkeypatch.setattr(audit_script.Audit, "get", no_refetch)
    assert audit_script.main() == 0
    assert summarize(tmp_path, {source}) == 0


@pytest.mark.parametrize("completed", [0, 1])
def test_main_detects_coverage_gaps_without_worker_exceptions(monkeypatch, tmp_path, capsys, completed):
    _cli(monkeypatch, tmp_path, {"price"}, ["2026-10-23", "2026-10-22"])
    twse = audit_script.Audit.twse
    monkeypatch.setattr(audit_script.Audit, "twse", lambda self, dates: twse(self, dates[:completed]))
    assert audit_script.main() == 1
    out = capsys.readouterr()
    assert f"missing {2 - completed}" in out.out and out.err == ""


def test_worker_failure_still_fails_when_all_results_were_recorded(monkeypatch, tmp_path, capsys):
    _cli(monkeypatch, tmp_path, {"price"}, ["2026-10-22"])
    twse = audit_script.Audit.twse

    def broken(self, dates):
        twse(self, dates)
        raise RuntimeError("worker cleanup failed")

    monkeypatch.setattr(audit_script.Audit, "twse", broken)
    assert audit_script.main() == 1
    out = capsys.readouterr()
    assert "missing 0" in out.out and "RuntimeError: worker cleanup failed" in out.err


@pytest.mark.parametrize("site,error", [
    ("get", ValueError("invalid cached JSON")),
    ("db", RuntimeError("connection failed")),
])
def test_cache_and_database_exceptions_fail_before_the_first_result(monkeypatch, tmp_path, capsys, site, error):
    _cli(monkeypatch, tmp_path, {"price"}, ["2026-10-22"])
    monkeypatch.setattr(audit_script.Audit, site, MagicMock(side_effect=error))
    assert audit_script.main() == 1
    out = capsys.readouterr()
    assert f"{type(error).__name__}: {error}" in out.err and "missing 1" in out.out
    assert summarize(tmp_path) == 1


def test_other_market_finishes_after_one_worker_fails(monkeypatch, tmp_path, capsys):
    _cli(monkeypatch, tmp_path, set(_SOURCES), ["2026-10-23", "2026-10-22"])
    get = audit_script.Audit.get

    def malformed(self, url, name):
        payload = get(self, url, name)
        if name == "mi_20261023.json":
            payload["tables"][0]["data"][0][:] = [None]
        return payload

    monkeypatch.setattr(audit_script.Audit, "get", malformed)
    assert audit_script.main() == 1
    assert "worker failed" in capsys.readouterr().err
    assert summarize(tmp_path, set(audit_script.TPEX_SOURCES)) == 0
    assert summarize(tmp_path, set(audit_script.TWSE_SOURCES)) == 1


def test_resume_retries_the_latest_error_after_an_older_success(monkeypatch, tmp_path):
    _cli(monkeypatch, tmp_path, {"price"}, ["2026-10-22"])
    assert audit_script.main() == 0
    audit_script.Audit(None, tmp_path, {"price"}).record("2026-10-22", "price", err="bad response")
    assert summarize(tmp_path) == 1
    assert audit_script.main() == 0
    assert summarize(tmp_path) == 0


def test_summary_detects_missing_sources_even_without_a_result_file(tmp_path, capsys):
    (tmp_path / "expected.json").write_text(json.dumps([
        ["2026-10-22", "t86"], ["2026-10-22", "tpex_price"],
    ]))
    assert summarize(tmp_path, {"tpex_price"}) == 1
    out = capsys.readouterr().out
    assert "tpex_price: 0 days" in out and "missing 1" in out
    assert "t86:" not in out


def test_summary_cli_checks_saved_coverage_without_opening_database(monkeypatch, tmp_path, capsys):
    (tmp_path / "expected.json").write_text(json.dumps([["2026-10-22", "price"]]))
    monkeypatch.setattr(audit_script.sys, "argv", [
        "audit", "--out", str(tmp_path), "--summary", "--sources", "price",
    ])
    engine = MagicMock(side_effect=AssertionError("離線彙總不能連 DB"))
    monkeypatch.setattr(audit_script, "get_engine", engine)
    assert audit_script.main() == 1
    assert "missing 1" in capsys.readouterr().out
    engine.assert_not_called()


def test_summary_empty_directory_does_not_certify_a_clean_audit(tmp_path):
    assert summarize(tmp_path) == 1


@pytest.mark.parametrize("source,before,first", [
    ("t86", "2012-05-01", "2012-05-02"),
    ("tpex_insti", "2018-01-12", "2018-01-15"),
])
def test_coverage_and_workers_share_source_start_dates(monkeypatch, tmp_path, source, before, first):
    _cli(monkeypatch, tmp_path, {source}, [first, before])
    assert audit_script.main() == 0
    assert json.loads((tmp_path / "expected.json").read_text()) == [[first, source]]
    rows = (tmp_path / "result.jsonl").read_text().splitlines()
    assert len(rows) == 1 and json.loads(rows[0])["date"] == first


def test_summary_plan_keeps_other_sources_and_previous_date_ranges(monkeypatch, tmp_path):
    _cli(monkeypatch, tmp_path, {"price"}, ["2026-10-22"])
    assert audit_script.main() == 0
    _cli(monkeypatch, tmp_path, {"tpex_price"}, ["2026-10-23"])
    assert audit_script.main() == 0
    assert summarize(tmp_path) == 0
    # 已規劃但缺少的舊範圍，不能被後一次成功執行覆蓋。
    (tmp_path / "expected.json").write_text(json.dumps([
        ["2026-10-21", "price"], ["2026-10-22", "price"], ["2026-10-23", "tpex_price"],
    ]))
    assert audit_script.main() == 0
    assert summarize(tmp_path, {"price"}) == 1
    assert summarize(tmp_path, {"tpex_price"}) == 0


@pytest.mark.parametrize("source", audit_script.TPEX_SOURCES)
@pytest.mark.parametrize("bad", [
    "115/08/28", None, "", "115/02/30", "115/13/22", "10000/10/22", "100000000000/10/22",
    "missing-date", "outer-date", "bad-stat", "empty-data", "no-tables",
])
def test_tpex_audit_rejects_unverifiable_tables_but_accepts_matching_dates(
    monkeypatch, tmp_path, source, bad,
):
    day = "2026-10-22"
    payload = _payload(source, day)
    broken = deepcopy(payload)
    if bad == "missing-date":
        del broken["tables"][0]["date"]
    elif bad == "outer-date":
        broken["date"] = "20261021"
    elif bad == "bad-stat":
        broken["stat"] = "error"
    elif bad == "empty-data":
        broken["tables"][0]["data"] = []
    elif bad == "no-tables":
        broken["tables"] = []
    else:
        broken["tables"][0]["date"] = bad
    audit = audit_script.Audit(None, tmp_path, {source})
    monkeypatch.setattr(audit, "get", lambda *args: broken)
    db = MagicMock(return_value={"2330": [Decimal(1)] * _WIDTH[source]})
    monkeypatch.setattr(audit, "db", db)
    audit.tpex([day])
    row = json.loads(audit.result.read_text().splitlines()[-1])
    assert row["err"] and "miss" not in row
    db.assert_not_called()
    assert summarize(tmp_path) == 1
    # 反向：相同數值、有效且相符的表內日期仍須照常比對。
    monkeypatch.setattr(audit, "get", lambda *args: payload)
    audit.tpex([day])
    row = json.loads(audit.result.read_text().splitlines()[-1])
    assert row["err"] is None and row["off"] == row["db"] == 1
    assert row["miss"] == row["extra"] == row["bad"] == 0
    assert summarize(tmp_path) == 0
