"""持倉快照 CLI 的估值契約；資料庫、行情與匯率均由接縫注入。"""

import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

import data_provider.base as provider  # noqa: E402
import dotenv  # noqa: E402
import sqlalchemy  # noqa: E402
import yfinance  # noqa: E402
from src.services import fund_service, portfolio_service  # noqa: E402


SCRIPT = Path(__file__).resolve().parents[1] / ".claude/skills/portfolio-check/snapshot.py"


def position(symbol="00631L.TW", currency="TWD", price=100, cost=80, quantity=1, available=True):
    return {
        "symbol": symbol, "name": symbol, "currency": currency, "quantity": quantity,
        "avg_cost": cost, "last_price": price, "price_available": available,
        "price_source": "history_close", "price_date": "2026-10-23",
    }


def account(*positions, currency="TWD", account_id=1):
    return {
        "account_id": account_id, "account_name": "測試帳戶", "base_currency": currency,
        "positions": list(positions),
    }


def fund(currency="TWD", value=100, nav=10):
    return {
        "fund_id": "TEST", "fund_name": "測試基金", "currency": currency,
        "market_value": value, "nav": nav, "nav_date": "2026-10-23", "pnl_pct": 25,
        "units": 10, "platform": "測試通路", "is_stale": False,
    }


@pytest.fixture
def run_snapshot(monkeypatch, capsys):
    def run(*accounts, rates=None, quotes=None, funds=(), argv=(), import_only=False):
        rates = {"TWD=X": 32, "JPYTWD=X": 0.2, **(rates or {})}
        svc = Mock()
        svc.get_portfolio_snapshot.return_value = {"accounts": list(accounts)}
        constructor = Mock(return_value=svc)
        fetcher = Mock()

        def quote(symbol):
            result = (quotes or {}).get(symbol)
            if isinstance(result, Exception):
                raise result
            return result

        fetcher.get_realtime_quote.side_effect = quote
        fund_svc = Mock()
        if isinstance(funds, Exception):
            fund_svc.list_holdings.side_effect = funds
        else:
            fund_svc.list_holdings.return_value = {"items": list(funds), "nav_error": None}
        fund_svc.get_detail.return_value = {
            "returns": {"m1": 1, "m6": 2, "y1": 3}, "risk": {"max_drawdown": -5}, "nav": 10,
        }
        fund_svc.get_nav_history.return_value = {"points": []}

        def ticker(symbol):
            if symbol == "0050.TW":
                return SimpleNamespace(history=Mock(side_effect=RuntimeError("離線基準")))
            value = rates[symbol]
            if isinstance(value, Exception):
                raise value
            return SimpleNamespace(fast_info={"last_price": value})

        ticker_mock = Mock(side_effect=ticker)
        conn = Mock()
        conn.execute.return_value.fetchone.return_value = None
        engine = Mock()
        engine.connect.return_value.__enter__ = Mock(return_value=conn)
        engine.connect.return_value.__exit__ = Mock(return_value=False)
        monkeypatch.setattr(portfolio_service, "PortfolioService", constructor)
        monkeypatch.setattr(provider, "DataFetcherManager", Mock(return_value=fetcher))
        monkeypatch.setattr(fund_service, "FundService", Mock(return_value=fund_svc))
        monkeypatch.setattr(yfinance, "Ticker", ticker_mock)
        monkeypatch.setattr(dotenv, "load_dotenv", Mock())
        monkeypatch.setattr(sqlalchemy, "create_engine", Mock(return_value=engine))
        monkeypatch.setattr(sys, "argv", [str(SCRIPT), *argv])
        runpy.run_path(str(SCRIPT), run_name="snapshot_test" if import_only else "__main__")
        return SimpleNamespace(
            output=capsys.readouterr().out, service=svc, constructor=constructor,
            fund_service=fund_svc, ticker=ticker_mock, conn=conn,
        )

    return run


def section(output, marker):
    return output.split(marker, 1)[1].split("==", 1)[0]


def row(output, symbol):
    return next(line.split() for line in output.splitlines() if line.startswith(symbol))


def test_import_has_no_database_or_network_side_effects(run_snapshot):
    result = run_snapshot(import_only=True)
    assert result.output == ""
    result.constructor.assert_not_called()
    result.ticker.assert_not_called()
    result.fund_service.list_holdings.assert_not_called()


@pytest.mark.parametrize("base,total", [("TWD", "3,300"), ("USD", "103")])
def test_each_position_is_converted_before_account_totals_and_weights(run_snapshot, base, total):
    result = run_snapshot(account(position(), position("AAPL", "USD"), currency=base))
    stocks = section(result.output, "== 帳戶")
    assert f"總市值 {total}" in stocks
    assert "97.0%" in " ".join(row(stocks, "AAPL"))
    assert "3.0%" in " ".join(row(stocks, "00631L.TW"))
    combined = section(result.output, "== 全部帳戶合併")
    assert "總市值 3,300" in combined
    assert "3,200" in row(combined, "AAPL")
    assert "100" in row(combined, "00631L.TW")
    result.service.get_portfolio_snapshot.assert_called_once_with(
        account_id=None, include_realtime=False, read_only=True,
    )


def test_other_account_currency_and_same_symbol_merge_with_funds(run_snapshot):
    result = run_snapshot(
        account(position("AAPL", "USD")),
        account(position("AAPL", "USD"), position("7203.T", "JPY"), currency="JPY", account_id=2),
        funds=[fund("JPY")],
    )
    combined = section(result.output, "== 全部帳戶合併")
    assert "總市值 6,440" in combined
    assert "6,400" in row(combined, "AAPL")
    assert "20" in row(combined, "7203.T")
    assert "20" in row(combined, "F:TEST")
    assert result.ticker.call_args_list.count((("JPYTWD=X",), {})) == 1


@pytest.mark.parametrize("price,available", [
    (0, False), (None, False), (100, False), (0, True), (float("nan"), True), (float("inf"), True),
])
def test_unavailable_price_never_becomes_a_loss_or_complete_concentration(run_snapshot, price, available):
    result = run_snapshot(account(position("6488.TWO", price=price, available=available), position()))
    stocks = section(result.output, "== 帳戶")
    missing = " ".join(row(stocks, "6488.TWO"))
    assert "無法取得" in missing
    assert "-100.0%" not in missing
    assert "%" not in missing
    assert "不完整" in stocks
    assert row(stocks, "00631L.TW")[-3:-1] == ["-", "+25.0%"]
    combined = section(result.output, "== 全部帳戶合併")
    assert "不完整" in combined
    assert "6488.TWO" in combined
    assert "%" not in combined


def test_all_unpriced_and_empty_accounts_continue_through_funds_and_analysis(run_snapshot):
    result = run_snapshot(account(position(price=0, available=False)), account(account_id=2), funds=[fund()])
    assert "== 帳戶 2" in result.output
    assert "== 基金（" in result.output
    assert "== 最近一次系統分析" in result.output
    assert "不完整" in section(result.output, "== 全部帳戶合併")
    assert "100" in row(section(result.output, "== 全部帳戶合併"), "F:TEST")


def test_realtime_quote_recovers_missing_history_and_zero_cost_only_hides_pnl(run_snapshot):
    live = SimpleNamespace(price=120, change_pct=2.5, source="SHIOAJI")
    result = run_snapshot(
        account(position(price=0, available=False, cost=0)), quotes={"00631L.TW": live},
    )
    stocks = section(result.output, "== 帳戶")
    fields = row(stocks, "00631L.TW")
    assert "總市值 120" in stocks and "不完整" not in stocks
    assert "120.00" in fields and "+2.50" in fields and "100.0%" in fields
    assert fields[-2:] == ["-", "SHIOAJI"]


@pytest.mark.parametrize("quote", [
    None, SimpleNamespace(price=0), SimpleNamespace(price=float("nan")), RuntimeError("報價失敗"),
])
def test_quote_failure_retains_valid_history_price_and_pnl(run_snapshot, quote):
    result = run_snapshot(account(position("2887A.TW")), quotes={"2887A.TW": quote}, argv=["1"])
    stocks = section(result.output, "== 帳戶")
    fields = row(stocks, "2887A.TW")
    assert "100.00" in fields and "+25.0%" in fields and "100.0%" in fields
    assert "history_close@2026-10-23" in fields
    assert "不完整" not in stocks
    result.fund_service.list_holdings.assert_not_called()
    assert result.service.get_portfolio_snapshot.call_args.kwargs["account_id"] == 1


@pytest.mark.parametrize("rate", [None, 0, -1, float("nan"), float("inf"), RuntimeError("缺匯率")])
def test_missing_fx_keeps_native_values_but_marks_combined_incomplete(run_snapshot, rate):
    result = run_snapshot(account(position("AAPL", "USD"), currency="USD"), rates={"TWD=X": rate})
    stocks = section(result.output, "== 帳戶")
    assert "總市值 100" in stocks and "100.0%" in stocks and "+25.0%" in stocks
    combined = section(result.output, "== 全部帳戶合併")
    assert "不完整" in combined and "AAPL" in combined and "%" not in combined
    assert "匯率" in result.output


def test_partial_symbol_and_missing_fund_do_not_show_complete_combined_weights(run_snapshot):
    result = run_snapshot(
        account(position("AAPL", "USD")),
        account(position("AAPL", "USD", price=None, available=False), account_id=2),
        funds=[fund(value=None, nav=None)],
    )
    combined = section(result.output, "== 全部帳戶合併")
    assert "不完整" in combined and "3,200" in combined and "%" not in combined
    assert "不完整" in " ".join(row(combined, "AAPL"))
    assert "無法取得" in " ".join(row(section(result.output, "== 基金（"), "測試基金"))


def test_fund_read_failure_marks_combined_incomplete(run_snapshot):
    result = run_snapshot(account(position()), funds=RuntimeError("基金不可用"))
    assert "基金持倉讀取失敗" in result.output
    combined = section(result.output, "== 全部帳戶合併")
    assert "不完整" in combined and "%" not in combined


def test_empty_portfolio_has_zero_total_without_incomplete_warning(run_snapshot):
    result = run_snapshot(account())
    assert "總市值 0" in section(result.output, "== 帳戶")
    combined = section(result.output, "== 全部帳戶合併")
    assert "總市值 0" in combined and "不完整" not in combined


def test_missing_foreign_rate_in_mixed_account_keeps_all_rows_and_stops_account_weights(run_snapshot):
    result = run_snapshot(
        account(position(), position("7203.T", "JPY")), rates={"JPYTWD=X": None},
    )
    stocks = section(result.output, "== 帳戶")
    assert "已知市值 100（不完整" in stocks
    for symbol in ("00631L.TW", "7203.T"):
        fields = row(stocks, symbol)
        assert "100.00" in fields
        assert fields[-3:-1] == ["-", "+25.0%"]
    combined = section(result.output, "== 全部帳戶合併")
    assert "無法取得" in row(combined, "7203.T")
    assert "%" not in combined


def test_valid_realtime_price_preserves_quantity_pnl_and_combined_weights(run_snapshot):
    quote = SimpleNamespace(price=120, change_pct=-1, source="SHIOAJI")
    result = run_snapshot(
        account(position("AAPL", "USD", quantity=2)), quotes={"AAPL": quote},
    )
    stocks = section(result.output, "== 帳戶")
    assert "總市值 7,680" in stocks
    fields = row(stocks, "AAPL")
    assert "120.00" in fields and "-1.00" in fields
    assert fields[-3:] == ["100.0%", "+50.0%", "SHIOAJI"]
    combined = section(result.output, "== 全部帳戶合併")
    assert row(combined, "AAPL")[-2:] == ["7,680", "100.0%"]


@pytest.mark.parametrize("missing", [None, ""])
def test_missing_position_currency_falls_back_to_account_base(run_snapshot, missing):
    result = run_snapshot(account(position("AAPL", missing), currency="USD"))
    stocks = section(result.output, "== 帳戶")
    assert "總市值 100" in stocks and "不完整" not in stocks
    assert row(stocks, "AAPL")[2] == "USD"
    assert "3,200" in row(section(result.output, "== 全部帳戶合併"), "AAPL")


def test_lowercase_position_currency_is_normalised_before_conversion(run_snapshot):
    result = run_snapshot(account(position("AAPL", "usd")))
    stocks = section(result.output, "== 帳戶")
    assert "總市值 3,200" in stocks and "不完整" not in stocks
