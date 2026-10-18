"""crawl_valuation_day 必須比對回應自帶的日期：parse 會把列蓋上「請求日」，
來源若對未發布日回 stat OK＋前一日的表，D-1 就會被存成 D、resume 再視為已完成。"""
from datetime import date

import pytest

from market_data import sources


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _payload(day):
    p = {"stat": "OK",
         "fields": ["證券代號", "證券名稱", "殖利率(%)", "股利年度",
                    "本益比", "股價淨值比", "財報年/季"],
         "data": [["2330", "台積電", "1.50", "114", "20.10", "5.50", "115/2"],
                  ["1101", "台泥", "3.38", "114", "12.00", "0.75", "115/2"]]}
    if day is not None:
        p["date"] = day
    return p


def _patch(monkeypatch, payload):
    seen = []

    def fake_get(url, **kwargs):
        seen.append(kwargs.get("params"))
        return _Resp(payload)

    monkeypatch.setattr(sources, "requests_get", fake_get)
    return seen


def test_matching_response_date_is_parsed(monkeypatch, capsys):
    seen = _patch(monkeypatch, _payload("20261016"))

    df = sources.crawl_valuation_day(date(2026, 10, 16))

    assert seen[0]["date"] == "20261016"
    assert float(df.loc[("2330", "2026-10-16"), "pe_ratio"]) == 20.10
    assert "WARN" not in capsys.readouterr().out


def test_previous_day_response_is_rejected_with_warn(monkeypatch, capsys):
    _patch(monkeypatch, _payload("20261015"))

    assert sources.crawl_valuation_day(date(2026, 10, 16)) is None

    out = capsys.readouterr().out
    assert "**WARN: BWIBBU_d 回應日期 20261015 ≠ 請求日 20261016" in out


@pytest.mark.parametrize("day", [None, ""])
def test_response_without_a_date_cannot_be_proven_fresh(monkeypatch, capsys, day):
    _patch(monkeypatch, _payload(day))

    assert sources.crawl_valuation_day(date(2026, 10, 16)) is None
    assert "WARN" in capsys.readouterr().out
