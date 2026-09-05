# -*- coding: utf-8 -*-
"""Watchlist API regressions for stock-code variant matching."""

from api.v1.endpoints.stocks import add_to_watchlist, get_watchlist, remove_from_watchlist
from api.v1.schemas.history import WatchlistRequest


class FakeSystemConfigService:
    def __init__(self, stock_list: str) -> None:
        self.stock_list = stock_list
        self.config_version = "cfg-v1"
        self.update_calls: list[str] = []

    def get_config(self, include_schema: bool = False) -> dict:
        return {
            "config_version": self.config_version,
            "items": [{"key": "STOCK_LIST", "value": self.stock_list}],
        }

    def update(self, **kwargs) -> None:
        items = kwargs["items"]
        self.stock_list = items[0]["value"]
        self.update_calls.append(self.stock_list)


def test_watchlist_add_deduplicates_raw_hk_code_against_prefixed_variant() -> None:
    service = FakeSystemConfigService("00700")

    response = add_to_watchlist(
        WatchlistRequest(stock_code="HK00700"),
        service=service,
    )

    assert response.stock_codes == ["00700"]
    assert service.stock_list == "00700"
    assert service.update_calls == []


def test_watchlist_remove_deletes_raw_hk_code_from_prefixed_variant_request() -> None:
    service = FakeSystemConfigService("00700")

    response = remove_from_watchlist(
        WatchlistRequest(stock_code="HK00700"),
        service=service,
    )

    assert response.stock_codes == []
    assert service.stock_list == ""
    assert service.update_calls == [""]


def test_watchlist_matching_is_case_insensitive_for_us_tickers() -> None:
    service = FakeSystemConfigService("aapl")

    add_response = add_to_watchlist(
        WatchlistRequest(stock_code="AAPL"),
        service=service,
    )
    remove_response = remove_from_watchlist(
        WatchlistRequest(stock_code="AAPL"),
        service=service,
    )

    assert add_response.stock_codes == ["aapl"]
    assert remove_response.stock_codes == []
    assert service.update_calls == [""]


def test_watchlist_reads_common_copy_paste_separators() -> None:
    service = FakeSystemConfigService("600519，300750  AAPL")

    response = get_watchlist(service=service)

    assert response.stock_codes == ["600519", "300750", "AAPL"]


def test_watchlist_add_normalizes_existing_mixed_separators_on_write() -> None:
    service = FakeSystemConfigService("600519，300750")

    response = add_to_watchlist(
        WatchlistRequest(stock_code="AAPL"),
        service=service,
    )

    assert response.stock_codes == ["600519", "300750", "AAPL"]
    assert service.stock_list == "600519,300750,AAPL"
    assert service.update_calls == ["600519,300750,AAPL"]


# --- 代码闸门必须只认 ASCII 数字/字母 ---------------------------------------
#
# ``_STOCK_CODE_RE`` 的注释宣称 "aligned with frontend validateStockCode"，而前端
# 那份 JS 正则的 ``\d`` 只认 ASCII。Python 的 ``\d`` 预设是 Unicode-aware，所以少了
# ``re.ASCII`` 这道闸门会放行全形与阿拉伯数字，让无效字元带着一个"合法"的代码身分
# 流进下游 fetcher —— 抓不到资料时 pipeline 刻意 fail-open，产出的是一份静默缺资料
# 的报告而不是一个明确的 400。

import pytest

from api.v1.endpoints.stocks import _STOCK_CODE_RE, _validate_and_normalize_stock_code
from fastapi import HTTPException


@pytest.mark.parametrize(
    "code",
    [
        "６００５１９",      # 全形 A 股 6 位
        "００７００.HK",     # 全形港股（原本还会被正规化成 HK００７００）
        "００６３１.TW",     # 全形台股 ETF
        "٠٠٦٣١.TW",      # 阿拉伯-印度数字
        "７２０３.T",       # 全形日股
        "００５９３０.KS",   # 全形韩股
    ],
)
def test_non_ascii_digits_never_pass_the_stock_code_gate(code: str) -> None:
    assert _STOCK_CODE_RE.match(code) is None
    with pytest.raises(HTTPException) as excinfo:
        _validate_and_normalize_stock_code(code)
    assert excinfo.value.detail["error"] == "invalid_stock_code"


@pytest.mark.parametrize(
    "code, expected",
    [
        ("2330.TW", "2330.TW"),
        ("2330.tw", "2330.TW"),      # 大小写不敏感必须保住（反向：拿掉 IGNORECASE 会红）
        ("00878.TW", "00878.TW"),
        ("006208.TW", "006208.TW"),  # 上游 #2312 把台股放宽到 4~6 位，别被 re.ASCII 连坐
        ("6488.TWO", "6488.TWO"),
        ("aapl", "aapl"),  # normalize 不对美股 ticker 转大写，大小写在 _watchlist_match_key 收敛
        ("600519", "600519"),
        ("7203.T", "7203.T"),
    ],
)
def test_ascii_codes_still_pass_after_tightening(code: str, expected: str) -> None:
    assert _STOCK_CODE_RE.match(code) is not None
    assert _validate_and_normalize_stock_code(code) == expected
