# -*- coding: utf-8 -*-
"""Watchlist API regressions for stock-code variant matching."""

import json

import pytest
from dotenv import dotenv_values
from fastapi import HTTPException
from pydantic import ValidationError

from api.v1.endpoints.stocks import (
    _serialize_watchlist_groups,
    _watchlist_match_key,
    add_to_watchlist,
    get_watchlist,
    get_watchlist_groups,
    remove_from_watchlist,
    save_watchlist_groups,
)
from api.v1.schemas.history import WatchlistRequest
from api.v1.schemas.stocks import WatchlistGroup, WatchlistGroupInput, WatchlistGroupsRequest
from src.services.system_config_service import ConfigConflictError


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


# --- 台股带尾字母的代码必须整条链都通 ---------------------------------------
#
# 槓桿 `00631L` / 反向 `00632R` / 债券 ETF `00679B` / 特别股 `2887A` 的尾字母是
# **载荷不是杂讯**。v3.31 那轮已经在 `market_symbol_utils.strip_optional_tw_letter`
# 把它放行，但 API 这道闸门与前端 `validation.ts` 当时都没跟上，於是这些代码
# 可以被分析、却不能加进自选、也拿不到 `/{stock_code}/profile`。
#
# 大小写那条同样是守门的一部分：闸门放行 `00631l.tw` 之後，若 `normalize_stock_code`
# 不把它收敛成 `00631L.TW`，同一档会以两种写法同时存在於 STOCK_LIST。

@pytest.mark.parametrize(
    "code, expected",
    [
        ("00631L.TW", "00631L.TW"),    # 元大台湾50正2
        ("00632R.TW", "00632R.TW"),    # 元大台湾50反1
        ("00679B.TWO", "00679B.TWO"),  # 债券 ETF（上柜）
        ("2887A.TW", "2887A.TW"),      # 台新金特别股
        ("00631l.tw", "00631L.TW"),    # 大小写必须收敛到同一个 canonical
        ("2887a.tw", "2887A.TW"),
    ],
)
def test_taiwan_letter_suffixed_codes_pass_the_gate_and_normalize(code: str, expected: str) -> None:
    assert _STOCK_CODE_RE.match(code) is not None
    assert _validate_and_normalize_stock_code(code) == expected


@pytest.mark.parametrize(
    "code",
    [
        "00631LL.TW",   # 反向：只放行**一个**字母，不是任意多个
        "631L.TW",      # 反向：数字位数仍受 4~6 位限制
        "0063110.TW",   # 反向：7 位数字
        "2330甲.TW",     # 汉字
        "00631Ｌ.TW",    # 全形字母
        "００６３１L.TW",   # 全形数字
    ],
)
def test_taiwan_letter_widening_does_not_admit_anything_else(code: str) -> None:
    assert _STOCK_CODE_RE.match(code) is None


# --- 注册指数与同码个股必须能共存於自选 ---------------------------------------

def test_watchlist_keeps_registered_index_and_same_digit_stock_apart() -> None:
    """`000016.SH`（上证50）与 `000016`（个股）是两个标的，不是同一个的两种写法。

    `normalize_stock_code` 会把 `.SH` 后缀剥掉，两者都塌成 `000016`；缺了 asset-aware
    的等价键，加了指数之後再加同码个股会被判成重复而**静默丢弃**——API 照样回
    「已加入」，列表却没变。上游 #2312 已让 Web 按 asset type 分别渲染两列。
    """
    service = FakeSystemConfigService("000016.SH")

    response = add_to_watchlist(WatchlistRequest(stock_code="000016"), service=service)

    assert response.stock_codes == ["000016.SH", "000016"]
    assert service.stock_list == "000016.SH,000016"


def test_watchlist_remove_targets_the_asset_the_caller_named() -> None:
    """反向：删个股不能把同码指数一起删掉（反之亦然）。"""
    service = FakeSystemConfigService("000016.SH,000016")

    remove_from_watchlist(WatchlistRequest(stock_code="000016"), service=service)
    assert service.stock_list == "000016.SH"

    service2 = FakeSystemConfigService("000016.SH,000016")
    remove_from_watchlist(WatchlistRequest(stock_code="000016.SH"), service=service2)
    assert service2.stock_list == "000016"


def test_stock_only_watchlist_equivalence_is_unchanged() -> None:
    """反向守门：asset-aware 只能作用在 INDEX 上。

    少了这条，一个「所有输入都改用 parse canonical」的过度实作也会过——而那会让
    `600519` 的键变成 `sh600519`、`2330.TW` 变成别的东西，等於把既有 STOCK_LIST
    的每一条都重新编码，旧资料一次全部对不上。
    """
    assert _watchlist_match_key("600519") == _watchlist_match_key("600519")
    assert _watchlist_match_key("600519") == "600519"
    assert _watchlist_match_key("00700") == _watchlist_match_key("00700.HK") == "HK00700"
    assert _watchlist_match_key("aapl") == _watchlist_match_key("AAPL") == "AAPL"
    assert _watchlist_match_key("2330.TW") == "2330.TW"


class FakeGroupedConfigService:
    """Multi-key fake: records whether both keys landed in one update call."""

    def __init__(self, stock_list: str, groups: str = "", conflict: bool = False) -> None:
        self.values = {"STOCK_LIST": stock_list}
        if groups:
            self.values["WATCHLIST_GROUPS"] = groups
        self.conflict = conflict
        self.update_calls: list[list[str]] = []

    def get_config(self, include_schema: bool = False) -> dict:
        return {
            "config_version": "cfg-v1",
            "items": [{"key": key, "value": value} for key, value in self.values.items()],
        }

    def update(self, **kwargs) -> None:
        if self.conflict:
            raise ConfigConflictError(current_version="cfg-v2")
        self.update_calls.append([item["key"] for item in kwargs["items"]])
        for item in kwargs["items"]:
            self.values[item["key"]] = item["value"]


def _groups_request(**groups) -> WatchlistGroupsRequest:
    return WatchlistGroupsRequest(
        groups=[WatchlistGroupInput(name=name, codes=codes) for name, codes in groups.items()]
    )


def test_watchlist_groups_unset_means_everything_ungrouped() -> None:
    service = FakeGroupedConfigService("2330.TW,AAPL")

    response = get_watchlist_groups(service=service)

    assert response.groups == []
    assert response.ungrouped == ["2330.TW", "AAPL"]


@pytest.mark.parametrize("raw", ["not json", "[1,2]", '"text"'])
def test_watchlist_groups_malformed_value_is_no_groups_not_an_error(raw: str) -> None:
    response = get_watchlist_groups(service=FakeGroupedConfigService("2330.TW", raw))

    assert response.groups == []
    assert response.ungrouped == ["2330.TW"]


def test_watchlist_groups_read_filters_codes_removed_outside_the_remove_endpoint() -> None:
    # 設定頁直接改 STOCK_LIST 時不會經過 remove，讀取必須自己過濾。
    service = FakeGroupedConfigService("2330.TW,AAPL", json.dumps({"科技": ["2330.TW", "2317.TW"]}))

    response = get_watchlist_groups(service=service)

    assert response.groups == [WatchlistGroup(name="科技", codes=["2330.TW"])]
    assert response.ungrouped == ["AAPL"]


def test_watchlist_remove_prunes_groups_in_the_same_write() -> None:
    service = FakeGroupedConfigService("2330.TW,AAPL", json.dumps({"科技": ["2330.TW", "AAPL"]}))

    remove_from_watchlist(WatchlistRequest(stock_code="2330.TW"), service=service)

    assert service.update_calls == [["STOCK_LIST", "WATCHLIST_GROUPS"]]
    assert json.loads(service.values["WATCHLIST_GROUPS"]) == {"科技": ["AAPL"]}
    # 空組保留：刪掉最後一檔不等於使用者要刪這個組。
    remove_from_watchlist(WatchlistRequest(stock_code="AAPL"), service=service)
    assert json.loads(service.values["WATCHLIST_GROUPS"]) == {"科技": []}


def test_watchlist_remove_without_groups_does_not_write_the_groups_key() -> None:
    service = FakeGroupedConfigService("2330.TW,AAPL")

    remove_from_watchlist(WatchlistRequest(stock_code="2330.TW"), service=service)

    assert service.update_calls == [["STOCK_LIST"]]


def test_watchlist_groups_save_keeps_order_and_leaves_stock_list_untouched() -> None:
    service = FakeGroupedConfigService("2330.TW,2317.TW,AAPL")

    response = save_watchlist_groups(
        _groups_request(美股=["AAPL"], 台股=["2317.TW", "2330.TW"]),
        service=service,
    )

    assert [group.name for group in response.groups] == ["美股", "台股"]
    assert response.groups[1].codes == ["2317.TW", "2330.TW"]
    assert response.ungrouped == []
    assert service.update_calls == [["WATCHLIST_GROUPS"]]
    assert service.values["STOCK_LIST"] == "2330.TW,2317.TW,AAPL"


def test_watchlist_groups_save_drops_foreign_codes_and_duplicate_membership() -> None:
    service = FakeGroupedConfigService("2330.TW,AAPL")

    response = save_watchlist_groups(
        _groups_request(甲=["2330.TW", "2317.TW"], 乙=["2330.TW", "AAPL"]),
        service=service,
    )

    assert response.groups[0].codes == ["2330.TW"]
    assert response.groups[1].codes == ["AAPL"]


def test_watchlist_groups_save_stores_the_raw_stock_list_spelling() -> None:
    # 指數身分靠原字串；分組存正規化後的值會和 STOCK_LIST 對不起來。
    service = FakeGroupedConfigService("aapl")

    response = save_watchlist_groups(_groups_request(美股=["AAPL"]), service=service)

    assert response.groups[0].codes == ["aapl"]


@pytest.mark.parametrize(
    ("groups", "error"),
    [
        ([("  ", [])], "invalid_group_name"),
        ([("甲", []), (" 甲 ", [])], "duplicate_group_name"),
    ],
)
def test_watchlist_groups_save_rejects_bad_names(groups: list, error: str) -> None:
    service = FakeGroupedConfigService("2330.TW")
    request = WatchlistGroupsRequest(
        groups=[WatchlistGroupInput(name=name, codes=codes) for name, codes in groups]
    )

    with pytest.raises(HTTPException) as exc:
        save_watchlist_groups(request, service=service)

    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == error
    assert service.update_calls == []


def test_watchlist_groups_save_reports_config_conflict() -> None:
    service = FakeGroupedConfigService("2330.TW", conflict=True)

    with pytest.raises(HTTPException) as exc:
        save_watchlist_groups(_groups_request(甲=["2330.TW"]), service=service)

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "config_conflict"


def test_watchlist_group_input_limits_lengths() -> None:
    with pytest.raises(ValidationError):
        WatchlistGroupInput(name="x" * 33, codes=[])
    with pytest.raises(ValidationError):
        WatchlistGroupInput(name="甲", codes=["x" * 33])


def test_watchlist_groups_serialization_survives_dotenv_round_trip(tmp_path) -> None:
    # 真的走 python-dotenv：組名含「 #」或 ${X} 時不跳脫就會被截斷或插值成壞 JSON。
    name = "半導體 #1 ${HOME} '引號\""
    env_file = tmp_path / ".env"
    line = _serialize_watchlist_groups([WatchlistGroup(name=name, codes=["2330.TW"])])
    env_file.write_text(f"WATCHLIST_GROUPS={line}\n", encoding="utf-8")

    assert json.loads(dotenv_values(env_file)["WATCHLIST_GROUPS"]) == {name: ["2330.TW"]}
