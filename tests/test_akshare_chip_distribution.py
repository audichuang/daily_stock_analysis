import pandas as pd
import pytest

from data_provider.akshare_fetcher import AkshareFetcher


@pytest.fixture
def cyq_spy(monkeypatch):
    import akshare as ak

    calls = []

    def fake_cyq(symbol):
        calls.append(symbol)
        return pd.DataFrame()

    monkeypatch.setattr(ak, "stock_cyq_em", fake_cyq)
    monkeypatch.setattr(AkshareFetcher, "_enforce_rate_limit", lambda self: None)
    return calls


@pytest.mark.parametrize("code", ["2383.TW", "6116.TWO", "7203.T", "005930.KS"])
def test_chip_skips_non_cn_suffix_markets_without_http(cyq_spy, code):
    # stock_cyq_em 只支持 A 股，且 akshare 内部请求无 timeout：非 A 股不得发起请求
    assert AkshareFetcher(sleep_min=0, sleep_max=0).get_chip_distribution(code) is None
    assert cyq_spy == []


def test_chip_still_queries_a_share(cyq_spy):
    AkshareFetcher(sleep_min=0, sleep_max=0).get_chip_distribution("600519")
    assert cyq_spy == ["600519"]
