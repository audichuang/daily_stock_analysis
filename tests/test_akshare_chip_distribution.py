import pandas as pd
import pytest

import data_provider.akshare_fetcher as ak_mod
from data_provider.akshare_fetcher import AkshareFetcher


@pytest.fixture
def cyq_spy(monkeypatch):
    calls = []

    def fake_call_with_timeout(func, *args, timeout=None, call_name="akshare", **kwargs):
        calls.append((call_name, kwargs.get("symbol"), timeout))
        return pd.DataFrame()

    monkeypatch.setattr(ak_mod, "_akshare_call_with_timeout", fake_call_with_timeout)
    monkeypatch.setattr(AkshareFetcher, "_enforce_rate_limit", lambda self: None)
    return calls


@pytest.mark.parametrize("code", ["2383.TW", "6116.TWO", "7203.T", "005930.KS", "AAPL", "00700.HK"])
def test_chip_skips_non_cn_markets_without_http(cyq_spy, code):
    # stock_cyq_em 是 A 股专属接口：非 A 股不得发起请求
    assert AkshareFetcher(sleep_min=0, sleep_max=0).get_chip_distribution(code) is None
    assert cyq_spy == []


def test_chip_queries_a_share_through_timeout_wrapper(cyq_spy):
    # akshare 内部请求无 timeout：A 股调用必须经有界等待的包装，不能直接调用
    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)
    fetcher.get_chip_distribution("600519")
    assert cyq_spy == [("stock_cyq_em", "600519", fetcher._history_call_timeout)]
