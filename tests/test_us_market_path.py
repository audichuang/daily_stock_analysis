# -*- coding: utf-8 -*-
"""美股路徑的守門測試。

這個 fork 長期只跑台股，美股路徑上累積了一批**不報錯、只給錯數字**的問題：
代碼轉換掉一種寫法、市場判定 fallback 到 A 股、幣別寫死人民幣、prompt 要求模型
分析一個它一格資料都沒有的欄位。共同形狀是「報告照出、測試照綠」，所以這裡的
每一項都斷言**可觀察的輸出**，而不是內部狀態。

每一項都做過 mutation 檢查：把修法改回舊寫法必須立刻紅。
"""

import pathlib
import tempfile
from unittest.mock import MagicMock, patch

import pytest


class TestUsSymbolsSurviveEveryLayer:
    """類別股（BRK.B／BRK-B）的兩種寫法都必須一路走到底。"""

    def test_dot_form_is_converted_to_yahoo_hyphen(self):
        """Yahoo 用 `BRK-B`；傳 `BRK.B` 回 0 筆，而 0 筆在上游各層都被當成正常降級。"""
        from data_provider.yfinance_fetcher import YfinanceFetcher

        fetcher = YfinanceFetcher()
        assert fetcher._convert_stock_code("BRK.B") == "BRK-B"
        assert fetcher._convert_stock_code("BF.B") == "BF-B"
        # 沒有分隔符的照舊，其他市場的轉換不受影響
        assert fetcher._convert_stock_code("AAPL") == "AAPL"
        assert fetcher._convert_stock_code("2330.TW") == "2330.TW"
        assert fetcher._convert_stock_code("hk00700") == "0700.HK"
        assert fetcher._convert_stock_code("600519") == "600519.SS"

    def test_both_yfinance_symbol_converters_agree(self):
        """有**兩份** yfinance 代碼轉換：行情 fetcher 一份，基本面 adapter 一份
        （它的 docstring 自己說是「lightweight inline reproduction」）。只修一份的話
        行情有了、基本面還是空的——實測就是這樣：報告出得來，估值那欄全是 N/A。
        """
        from data_provider.yfinance_fetcher import YfinanceFetcher
        from data_provider.yfinance_fundamental_adapter import _convert_to_yf_symbol

        fetcher = YfinanceFetcher()
        for code in ("AAPL", "BRK.B", "BF.B", "2330.TW", "0700.HK", "HK00700"):
            assert fetcher._convert_stock_code(code) == _convert_to_yf_symbol(code), code

    def test_exchange_suffix_is_not_mistaken_for_a_class_share(self):
        """`.US` 是交易所後綴不是類別股——認成類別股會造出 Yahoo 不懂的 `AAPL-US`。"""
        from data_provider import is_us_stock_code

        assert is_us_stock_code("BRK.B") and is_us_stock_code("BRK-B")
        assert not is_us_stock_code("AAPL.US")

    @pytest.mark.parametrize("code", ["AAPL", "BRK.B", "BRK-B", "BF-B", "AAPL.US"])
    def test_every_us_form_is_tagged_us_not_a_share(self, code):
        """判不出美股不是查詢失敗，是**默默落到 A 股預設**。

        後果是 prompt 開頭寫「你是一位 A 股投资分析师」，並要模型按 ±10% 漲跌停與
        T+1 交割去推理一檔美股——一份看起來完整、實際上前提全錯的報告。
        """
        from src.market_context import detect_market
        from src.services.stock_code_utils import resolve_daily_stock_identity

        assert detect_market(code) == "us"
        assert resolve_daily_stock_identity(code).market == "us"


class TestEtfDetectionDoesNotSwallowOperatingCompanies:
    """ETF 判定用整詞匹配，不是子字串。"""

    @pytest.mark.parametrize("code,name", [
        ("SPY", "SPDR S&P 500 ETF TRUST"),
        ("QQQ", "INVESCO QQQ TRUST"),
        ("VOO", "VANGUARD INDEX FUNDS S&P 500 ETF"),
    ])
    def test_real_etfs_are_still_detected(self, code, name):
        from src.search_service import SearchService

        assert SearchService.is_index_or_etf(code, name) is True

    @pytest.mark.parametrize("code,name", [
        ("UNH", "UNITEDHEALTH GROUP"),   # 'UNIT' 是 'UNITEDHEALTH' 的子字串
        ("UNP", "UNION PACIFIC"),
        ("AAPL", "APPLE INC"),
        ("NTRS", "Northern Trust Corporation"),   # 整詞的 TRUST 也騙得過名稱啟發式
        ("AAT", "AMERICAN ASSETS TRUST"),         # 約 192 檔 REIT 同形狀
    ])
    def test_operating_companies_are_not_flagged_as_etf(self, code, name):
        """被誤判成 ETF 的個股會**整組失去公司風險／財報／競爭檢索**，只剩指數式查詢。"""
        from src.search_service import SearchService

        assert SearchService.is_index_or_etf(code, name) is False

    def test_us_verdict_comes_from_the_official_type_not_the_name(self):
        """名稱關鍵詞分不開 `Northern Trust` 與 `Invesco QQQ Trust`——所以美股改讀
        `stocks.index.json` 的 type（由 NASDAQ Trader 的 ETF 欄位填）。
        """
        from src.data.stock_index_loader import get_us_asset_type

        assert get_us_asset_type("QQQ") == "etf"
        assert get_us_asset_type("NTRS") == "stock"
        # 其他市場整欄都是預設值，沒帶資訊 ⇒ 必須回 None 讓呼叫端 fallback，
        # 否則台股 ETF 會被判成個股
        assert get_us_asset_type("2330.TW") is None
        assert get_us_asset_type("510300") is None

    def test_a_share_etf_prefix_still_wins(self):
        """A 股 ETF 靠代碼前綴判定，必須排在索引查詢之前。"""
        from src.search_service import SearchService

        assert SearchService.is_index_or_etf("510300", "沪深300ETF") is True

    def test_us_index_names_are_readable_not_refinitiv_mangles(self):
        """這串會變成報告標題、prompt 開頭與五個新聞檢索維度的搜尋字串。"""
        from src.data.stock_index_loader import get_index_stock_name

        for code, expected in [("AMAT", "Applied Materials"), ("TSM", "Taiwan Semiconductor"),
                               ("UNH", "UnitedHealth"), ("AAPL", "Apple")]:
            name = get_index_stock_name(code) or ""
            assert expected in name, f"{code}: {name!r}"
            assert "ADR" not in name and ":" not in name, f"{code}: {name!r}"


class TestPricesAreQuotedInTheMarketsOwnCurrency:
    def test_amount_currency_follows_the_market(self):
        from src.analyzer import GeminiAnalyzer

        fmt = GeminiAnalyzer._format_amount
        stub = MagicMock()
        assert fmt(stub, 1.1575e10, "us") == "115.75 亿美元"
        assert fmt(stub, 1.1575e10, "hk") == "115.75 亿港元"
        assert fmt(stub, 1.1575e10, "tw") == "115.75 亿新台币"

    def test_a_share_output_is_byte_for_byte_unchanged(self):
        """幣別是**加上去**的，A 股與未知市場必須跟改動前一模一樣。"""
        from src.analyzer import GeminiAnalyzer

        fmt = GeminiAnalyzer._format_amount
        stub = MagicMock()
        for value, expected in ((1.1575e10, "115.75 亿元"), (5.0e4, "5.00 万元"), (300.0, "300 元")):
            assert fmt(stub, value, "cn") == expected
            assert fmt(stub, value) == expected        # 預設值
            assert fmt(stub, value, "zz") == expected  # 未知市場


def _analyzer(region, language="zh-TW"):
    from src.core.market_profile import get_profile
    from src.core.market_strategy import get_market_strategy_blueprint
    from src.market_analyzer import MarketAnalyzer

    cfg = MagicMock()
    cfg.market_review_region = region
    cfg.market_review_color_scheme = "green_up"
    cfg.report_language = language

    ma = MarketAnalyzer.__new__(MarketAnalyzer)
    ma.analyzer = MagicMock()
    ma.config = cfg
    ma.profile = get_profile(region)
    ma.strategy = get_market_strategy_blueprint(region)
    ma.region = region
    return ma


def _overview(**kw):
    from src.market_analyzer import MarketIndex, MarketOverview

    ov = MarketOverview(date="2026-08-07")
    ov.indices = [MarketIndex(code="SPX", name="标普500指数", current=6400.0,
                              change=30.0, change_pct=0.47, amount=5.2e9)]
    for name, value in kw.items():
        setattr(ov, name, value)
    return ov


class TestZhTwPromptRespectsMarketCapabilities:
    """zh-TW 的複盤 prompt 以前把版面寫死，不看 profile 能力旗標。"""

    @staticmethod
    def _prompt(region):
        from src.market_analyzer import MarketAnalyzer

        ma = _analyzer(region)
        with patch.object(MarketAnalyzer, "_get_review_language", return_value="zh-TW"), \
             patch.object(MarketAnalyzer, "_get_output_language", return_value="zh-TW"), \
             patch.object(MarketAnalyzer, "_get_strategy_prompt_block", return_value=""), \
             patch.object(MarketAnalyzer, "_get_index_hint", return_value="HINT"):
            return MarketAnalyzer._build_review_prompt(ma, _overview(), [])

    def test_us_is_not_asked_for_data_that_does_not_exist(self):
        """美股沒有漲跌停制度、沒有板塊榜。要模型分析它們，模型就會編。"""
        prompt = self._prompt("us")
        headings = [line for line in prompt.splitlines() if line.startswith("### ")]

        assert not any("資金與情緒" in h for h in headings), "美股無漲跌家數／漲跌停，不該有這節"
        assert not any("板塊主線" in h for h in headings), "美股無板塊榜，不該有這節"
        assert "消息催化" in prompt and "風險提示" in prompt, "其餘章節必須還在"

    def test_us_prompt_states_the_data_boundary(self):
        """光是拿掉章節不夠——還要明講「這些資料沒有」，否則模型會自己補。"""
        prompt = self._prompt("us")

        assert "資料邊界" in prompt, "缺少邊界要求，模型會補寫未提供的寬度／資金流"
        assert "暂无涨跌家数" in prompt or "暫無漲跌家數" in prompt

    def test_tw_keeps_the_sections_it_has_data_for(self):
        """台股有完整漲跌家數與成交額，這一節不能被順手關掉。"""
        prompt = self._prompt("tw")
        headings = [line for line in prompt.splitlines() if line.startswith("### ")]

        assert any("資金與情緒" in h for h in headings)


class TestTemplateFallbackStaysInTheReportLanguage:
    def test_us_zh_tw_strategy_block_is_not_english(self):
        """模板路徑不是罕見路徑：LLM 回空（實測 BRK.B 連兩次）就會走到這裡。

        `to_markdown_block()` 的標題只看 region，`us` 一律回英文，於是 zh-TW 的
        美股模板報告會在兩個中文章節之間夾一段 "### VI. Strategy Framework"。
        """
        from src.market_analyzer import MarketAnalyzer

        block = MarketAnalyzer._get_strategy_markdown_block(_analyzer("us"), "zh-TW")

        assert "### 六、策略框架" in block, block
        assert "Strategy Framework" not in block
        assert "趨勢結構" in block, "zh-TW 應為繁體"


class TestIndexTableUnitFollowsTheMarket:
    @pytest.mark.parametrize("region,unit", [
        ("us", "十億美元"), ("tw", "新台幣億元"), ("cn", "億"),
    ])
    def test_turnover_column_header_matches_the_divisor(self, region, unit):
        """`_format_turnover_value` 對 us/hk/jp/kr 除的是 1e9，表頭寫死「亿」會差 10 倍且幣別錯。"""
        from src.market_analyzer import MarketAnalyzer

        ma = _analyzer(region)
        with patch.object(MarketAnalyzer, "_get_review_language", return_value="zh-TW"):
            header = MarketAnalyzer._build_indices_block(ma, _overview()).splitlines()[0]

        assert f"成交額({unit})" in header, header


class TestVixNeverEntersTheDirectionalAverage:
    def test_score_and_its_stated_reason_use_the_same_filter(self):
        """分數已排除 VIX，理由文案以前沒有——risk-off 當天會印出一個正的平均漲跌幅。"""
        from src.market_analyzer import MarketAnalyzer, MarketIndex

        ma = _analyzer("us")
        overview = _overview(indices=[
            MarketIndex(code="SPX", name="标普500指数", current=6200.0, change=-126.0, change_pct=-2.0),
            MarketIndex(code="IXIC", name="纳斯达克综合指数", current=20000.0, change=-512.0, change_pct=-2.5),
            MarketIndex(code="VIX", name="VIX恐慌指数", current=30.0, change=6.0, change_pct=25.0),
        ])
        zh = " ".join(MarketAnalyzer._build_market_light_reasons_zh(ma, overview, 24))
        en = " ".join(MarketAnalyzer._build_market_light_reasons_en(ma, overview, 24))

        # 三檔方向性指數平均 -2.25%；把 VIX 的 +25% 算進去會變成 +6.83%
        assert "主要指数平均涨跌幅 -2.25%" in zh, zh
        assert "average major-index change -2.25%" in en, en


class TestUsValuationSurvivesTheNameFastPath:
    """美股的 pe/pb 以前恆為 None，而 valuation 區塊照樣回報 status=ok。

    成因是兩個最佳化互撞：yfinance 的行情路徑**只在本地查不到股票名稱時**才抓
    `ticker.info`（為了保住看板的零網路快路徑），而本 fork 補齊了美股名稱索引
    ⇒ 名稱一律本地命中 ⇒ `ticker_info` 恆為空 ⇒ 估值跟著消失。索引補得越好、
    估值掉得越多，而且下游看到的是「ok」。
    """

    def test_bundle_exposes_valuation_from_the_info_it_already_fetched(self):
        from data_provider.yfinance_fundamental_adapter import YfinanceFundamentalAdapter

        info = {"trailingPE": 35.97, "priceToBook": 42.57, "currency": "USD"}
        ticker = MagicMock()
        ticker.get_info.return_value = info
        with patch("yfinance.Ticker", return_value=ticker):
            bundle = YfinanceFundamentalAdapter().get_fundamental_bundle("AAPL")

        assert bundle["valuation"] == {"pe_ratio": 35.97, "pb_ratio": 42.57}
        assert "valuation:yfinance.info" in bundle["source_chain"]

    def test_missing_quote_ratios_are_backfilled_from_the_bundle(self):
        from types import SimpleNamespace

        from data_provider import DataFetcherManager

        manager = DataFetcherManager(fetchers=[])
        cfg = SimpleNamespace(
            enable_fundamental_pipeline=True,
            fundamental_cache_ttl_seconds=0,
            fundamental_stage_timeout_seconds=2.0,
            fundamental_fetch_timeout_seconds=1.5,
            fundamental_retry_max=1,
        )
        # 這就是實測到的形狀：市值有、比率全空
        quote = SimpleNamespace(
            pe_ratio=None, pb_ratio=None, total_mv=4.57e12, circ_mv=None,
            source=SimpleNamespace(value="fallback"),
        )
        bundle = {
            "status": "partial",
            "valuation": {"pe_ratio": 35.97, "pb_ratio": 42.57},
            "growth": {}, "earnings": {}, "belong_boards": [],
            "source_chain": ["valuation:yfinance.info"], "errors": [],
        }
        with patch("src.config.get_config", return_value=cfg), \
             patch.object(manager, "get_realtime_quote", return_value=quote), \
             patch("data_provider.yfinance_fundamental_adapter."
                   "YfinanceFundamentalAdapter.get_fundamental_bundle", return_value=bundle):
            ctx = manager.get_fundamental_context("AAPL")

        assert ctx["valuation"]["data"]["pe_ratio"] == 35.97
        assert ctx["valuation"]["data"]["pb_ratio"] == 42.57
        providers = [entry.get("provider") for entry in ctx["valuation"]["source_chain"]]
        assert "yfinance_fundamental_bundle" in providers, providers


class TestValuationRatiosReachTheModelNotJustThePayload:
    def test_prompt_falls_back_to_the_fundamental_block(self):
        """把 pe/pb 補進 `fundamental_context` 但 prompt 讀 quote，等於沒補。

        兩者來自同一次執行的 `ticker.info`，而 quote 的 yfinance 路徑在本地命中
        股票名稱時會跳過那次抓取（美股幾乎必然命中）⇒ 模型看到的是「本益比 N/A」，
        正確數字就在同一個 context 的另一個 key 裡。
        """
        from src.analyzer import GeminiAnalyzer

        context = {
            "code": "NVDA",
            "stock_name": "英伟达",
            "today": {"close": 223.96, "open": 220.0, "high": 225.0, "low": 219.0},
            "realtime": {"price": 223.96, "pe_ratio": None, "pb_ratio": None},
            "fundamental_context": {
                "valuation": {"status": "ok", "data": {"pe_ratio": 34.24, "pb_ratio": 27.75}},
            },
        }
        stub = MagicMock(spec=GeminiAnalyzer)
        stub._get_skill_prompt_sections.return_value = ("", "", True)
        stub._format_amount = GeminiAnalyzer._format_amount.__get__(stub)
        prompt = GeminiAnalyzer._format_prompt(stub, context, "英伟达", report_language="zh-TW")

        assert "34.24" in prompt, "本益比沒有進到 prompt"
        assert "27.75" in prompt, "股價淨值比沒有進到 prompt"


class TestYfinanceIsNotSelfLabelledAsDegradedWhereItIsThePrimary:
    """`source=="fallback"` 會讓 `analysis_context_builder` 判定行情降級 ⇒ 品質分被扣、
    報告印出「核心行情受限」、LLM 的「高」信心被改寫成「中」。美股每一次都吃這一刀，
    而 yfinance 正是美股的指定主來源，什麼都沒降級。
    """

    @pytest.mark.parametrize("market,expected", [
        ("us", "yfinance"), ("jp", "yfinance"), ("kr", "yfinance"),
    ])
    def test_primary_markets_report_yfinance(self, market, expected):
        from data_provider.yfinance_fetcher import _source_for_market

        assert _source_for_market(market).value == expected

    @pytest.mark.parametrize("market", ["tw", "cn", "hk", None])
    def test_taiwan_keeps_the_shioaji_downgrade_signal(self, market):
        """台股必須維持 `fallback`：`source` 由 shioaji 變成它，正是本 fork 用來辨識
        「金鑰沒注入、已靜默降級成延遲報價」的訊號（AGENTS.md §10）。
        """
        from data_provider.yfinance_fetcher import _source_for_market

        assert _source_for_market(market).value == "fallback"


class TestIndexAliasNamesMatchThePricesTheyCarry:
    def test_djia_names_the_index_it_prices(self):
        """`DJIA` 同時是道瓊的通用縮寫與一檔掛牌 ETF。行情走 US_INDEX_MAPPING 取到
        ^DJI 的五萬多點，名稱若從 stocks.index.json 取就變成那檔 ETF ⇒ 標題與數字
        差三個數量級，而且兩邊都「有值」。
        """
        from data_provider import DataFetcherManager

        name = DataFetcherManager().get_stock_name("DJIA", allow_realtime=False)

        assert name == "道琼斯工业指数", name
        assert "ETF" not in (name or "")


class TestUsDailyChainPrefersYfinance:
    def test_alphavantage_does_not_sit_ahead_of_yfinance(self):
        """AlphaVantage 回未復權價且單次上限 100 根；排在前面的話，設了金鑰之後
        最近 100 根裡的除權息會印出錯的 pct_chg，同一天收盤價還會隨執行次數變動。
        """
        import inspect

        from data_provider.base import DataFetcherManager

        src = inspect.getsource(DataFetcherManager.get_daily_data)
        order_line = next(
            line for line in src.splitlines()
            if "source_order = [" in line and "LongbridgeFetcher\"]" in line
            and "prefer_lb" not in line and "Yfinance" in line and "AlphaVantage" in line
        )
        assert order_line.index("YfinanceFetcher") < order_line.index("AlphaVantageFetcher"), order_line

    def test_priority_resort_cannot_demote_the_pinned_first_source(self):
        """上游 #2250 之后 `source_order` 会再过一次 `_order_us_sources_by_priority`。

        预设优先级是 Finnhub=2 < AlphaVantage=3 < Yfinance=4，所以 `pin_first=False`
        会把上面那条字面顺序**无声重排回去**、AlphaVantage 又跑到 yfinance 前面。
        本 fork 三条链路的首选都是刻意锚定的，故呼叫点一律 `pin_first=True`。
        """
        import inspect
        import threading

        from data_provider.base import DataFetcherManager

        src = inspect.getsource(DataFetcherManager.get_daily_data)
        assert "_order_us_sources_by_priority(source_order, pin_first=True)" in src, (
            "US 路由必须锚定首选；pin_first 一旦跟随上游改回 is_us_index/prefer_lb，"
            "普通美股的 yfinance 首选就会被 *_PRIORITY 排序无声推翻"
        )

        # 锚定的行为面：预设优先级下 yfinance 仍在首位，其余兜底成员照样按优先级重排。
        class _F:
            def __init__(self, name, priority):
                self.name, self.priority = name, priority

        # Finnhub 刻意給 7：兜底段的優先級順序必須與 `fork_order` 的字面順序**不同**，
        # 否則期望值等於輸入值，一個「pin_first=True 就原樣回傳」的空實作也會過。
        fetchers = [
            _F("FinnhubFetcher", 7),
            _F("AlphaVantageFetcher", 3),
            _F("YfinanceFetcher", 4),
            _F("LongbridgeFetcher", 5),
        ]
        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = list(fetchers)
        manager._fetchers_lock = threading.RLock()
        manager._fetchers_by_name = {f.name: f for f in fetchers}
        manager._fetcher_call_locks = {}
        manager._fetcher_call_locks_lock = manager._fetchers_lock
        manager._stock_name_cache = {}
        manager._stock_name_cache_lock = manager._fetchers_lock

        fork_order = [
            "YfinanceFetcher", "FinnhubFetcher", "AlphaVantageFetcher", "LongbridgeFetcher",
        ]
        # 首選鎖住，其餘三個按 priority 重排（3 < 5 < 7）——與輸入順序不同，
        # 所以原樣回傳的空實作會紅。
        assert manager._order_us_sources_by_priority(fork_order, pin_first=True) == [
            "YfinanceFetcher", "AlphaVantageFetcher", "LongbridgeFetcher", "FinnhubFetcher",
        ]
        # 反向：不錨定就會被優先級推翻——這正是要擋的那個形狀。
        assert manager._order_us_sources_by_priority(fork_order, pin_first=False)[0] == (
            "AlphaVantageFetcher"
        )


class TestRecapIsDatedByTheMarketNotTheServerClock:
    def test_us_recap_uses_the_new_york_session_not_the_taipei_date(self):
        """台北時間任何時刻，美股最近收完的那場都是紐約的前一天。"""
        from datetime import date

        from src.market_analyzer import MarketAnalyzer

        ma = _analyzer("us")
        with patch("src.market_analyzer.get_effective_trading_date",
                   return_value=date(2026, 8, 10)) as spy, \
             patch.object(MarketAnalyzer, "_get_main_indices", return_value=[]):
            overview = MarketAnalyzer.get_market_overview(ma)

        # P1-4：時鐘只讀一次，顯式傳給每個判定——斷言「同一個讀數有傳進去」，
        # 而不是舊的不帶時間簽名（那會讓三次獨立讀鐘的矛盾無法被測到）
        assert spy.call_count == 1
        assert spy.call_args.args == ("us",)
        assert spy.call_args.kwargs["current_time"].tzinfo is not None
        assert overview.date == "2026-08-10"


class TestEmptyLlmResponseNamesItsCause:
    """「LLM returned empty response」在实测里同时对应两件完全不同的事：金钥／服务挂了，
    以及**推理模型把 token 预算烧在推理上、还没产出内容就到顶**。後者的
    `finish_reason` 是 `length`，不带上它就得另做一轮诊断才分得出来。

    实测 `deepseek/deepseek-v4-flash`：`max_tokens=2048`（本仓库预设）0/3 有内容，
    8192 下 2/3 有内容。
    """

    @staticmethod
    def _response(finish_reason):
        choice = MagicMock()
        choice.finish_reason = finish_reason
        choice.message.content = ""
        choice.message.content_blocks = None
        choice.content_blocks = None
        choice.content = None
        response = MagicMock()
        response.choices = [choice]
        return response

    @pytest.mark.parametrize("reason", ["length", "stop"])
    def test_finish_reason_is_reported(self, reason):
        from src.llm.client import LLMClient

        client = LLMClient.__new__(LLMClient)
        assert client._finish_reason_of(self._response(reason)) == reason

    def test_no_choices_does_not_raise(self):
        from src.llm.client import LLMClient

        client = LLMClient.__new__(LLMClient)
        empty = MagicMock()
        empty.choices = []
        assert client._finish_reason_of(empty) == ""


class TestMarketGatingSpansTheDateLine:
    """台北週一早上，紐約還是週日 ⇒ 只看市場當地日期會把 `us` 丟掉，
    而週五那場美股收在台北週一 04:00，正是晨間例行要讀的東西。
    實測破口：台北週六約 13:00 到週一約 12:00，其間 `tw,us` 會塌成 `tw`。
    """

    @staticmethod
    def _at(day, hour):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from src.core.trading_calendar import get_open_markets_today

        return get_open_markets_today(datetime(2026, 8, day, hour, 0, tzinfo=ZoneInfo("Asia/Taipei")))

    def test_us_survives_taipei_monday_morning(self):
        assert "us" in self._at(10, 9), "台北週一早上丟掉美股 = 晨間例行讀不到週五收盤"
        assert "tw" in self._at(10, 9)

    def test_taipei_saturday_morning_still_carries_the_friday_us_session(self):
        """市場當地日期那半邊不能拿掉：台北週六早上紐約還是週五。"""
        assert "us" in self._at(8, 9)

    @pytest.mark.parametrize("day,hour", [(8, 14), (9, 10)])
    def test_genuinely_dead_days_stay_closed(self, day, hour):
        """修法是聯集不是放寬——真的沒有新資料的時段仍然不跑。"""
        markets = self._at(day, hour)
        assert "us" not in markets and "tw" not in markets


class TestNoPhantomBarBeforeTheSessionOpens:
    """台北 12:00~21:30 跑美股時，紐約當天是交易日但盤還沒開。舊的閘門只問
    「今天是不是交易日」，於是會用「即時價」（其實是昨收）複製出一根 OHLC 與量
    都跟前一根相同的假日線，指標全在它上面算。實測 AAPL signal_score 46→55。
    """

    @staticmethod
    def _phase(market, day, hour):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from src.core.trading_calendar import infer_market_phase

        return infer_market_phase(market, datetime(2026, 8, day, hour, 0, tzinfo=ZoneInfo("Asia/Taipei")))

    @pytest.mark.parametrize("hour", [12, 14, 18])
    def test_us_is_premarket_through_the_taipei_afternoon(self, hour):
        from src.core.trading_calendar import MarketPhase

        assert self._phase("us", 11, hour) is MarketPhase.PREMARKET

    def test_post_close_is_not_blocked(self):
        """收盤後那筆即時價就是當日收盤，DB 日線還沒進來時仍該補——不能一起關掉。"""
        from src.core.trading_calendar import MarketPhase

        assert self._phase("us", 11, 9) is MarketPhase.POSTMARKET
        assert self._phase("tw", 11, 14) is MarketPhase.POSTMARKET

    @staticmethod
    def _run(phase):
        """跑真正的 `_augment_historical_with_realtime`，只墊掉時鐘與市場判定。

        兩個必須做對、否則測試會因為**別的理由**通過（mutation 檢查抓到過）：
        quote 一定要有真的 `price`（否則函式在最前面就 return），且最後一根 K 棒的
        日期必須**早於** market_today（否則走的是「更新最後一列」而不是 append）。
        """
        from datetime import date, datetime
        from zoneinfo import ZoneInfo

        import pandas as pd

        from src.core.pipeline import StockAnalysisPipeline

        df = pd.DataFrame({
            "date": [date(2026, 8, 6), date(2026, 8, 7)],
            "open": [310.0, 311.0], "high": [312.0, 313.0],
            "low": [309.0, 310.0], "close": [311.0, 312.0], "volume": [1e6, 1.1e6],
        })
        quote = MagicMock(price=312.0, open_price=312.0, high=312.0, low=312.0,
                          volume=0, amount=None, change_pct=0.0, pre_close=312.0)

        stub = MagicMock(spec=StockAnalysisPipeline)
        stub.config = MagicMock(enable_realtime_technical_indicators=True)
        ny_now = datetime(2026, 8, 11, 8, 0, tzinfo=ZoneInfo("America/New_York"))
        with patch("src.core.pipeline.get_market_for_stock", return_value="us"), \
             patch("src.core.pipeline.get_market_now", return_value=ny_now), \
             patch("src.core.pipeline.is_market_open", return_value=True), \
             patch("src.core.pipeline.infer_market_phase", return_value=phase):
            return df, StockAnalysisPipeline._augment_historical_with_realtime(stub, df, quote, "AAPL")

    def test_premarket_appends_nothing(self):
        from src.core.trading_calendar import MarketPhase

        df, out = self._run(MarketPhase.PREMARKET)
        assert len(out) == len(df), "開盤前補了一根假 K 棒"

    @pytest.mark.parametrize("phase_name", ["INTRADAY", "LUNCH_BREAK", "CLOSING_AUCTION", "POSTMARKET"])
    def test_every_phase_after_the_open_still_appends(self, phase_name):
        """這個修法只擋開盤前。盤中疊即時價是它本來的用途；**收盤後那筆即時價就是
        當日收盤**，DB 日線還沒進來時仍該補——台北 09:00 讀美股、14:00 讀台股都在
        這一格，一起關掉會讓當天整個消失。
        """
        from src.core.trading_calendar import MarketPhase

        df, out = self._run(getattr(MarketPhase, phase_name))
        assert len(out) == len(df) + 1, f"{phase_name} 不再補當日 K 棒 = 修過頭"


class TestCodexReviewFindings:
    """獨立對抗審查抓到的十項，全部在此釘住。"""

    def test_recap_date_matches_the_session_the_prices_belong_to(self):
        """兩個方向都會錯：用伺服器日期，美股永遠早一天；一律用「上一場已收盤」，
        台股盤中會把當天正在形成的那根標成上週五，而 daily_market_context 直接信它。
        """
        from datetime import date, datetime
        from zoneinfo import ZoneInfo

        import src.market_analyzer as ma_mod
        from src.core.trading_calendar import MarketPhase
        from src.market_analyzer import MarketAnalyzer

        stub = MagicMock(spec=MarketAnalyzer)
        stub.region = "tw"
        tw_now = datetime(2026, 8, 10, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))
        with patch.object(ma_mod, "infer_market_phase", return_value=MarketPhase.INTRADAY), \
             patch.object(ma_mod, "get_market_now", return_value=tw_now), \
             patch.object(ma_mod, "get_effective_trading_date", return_value=date(2026, 8, 7)):
            assert MarketAnalyzer._resolve_overview_date(stub) == date(2026, 8, 10)

        with patch.object(ma_mod, "infer_market_phase", return_value=MarketPhase.PREMARKET), \
             patch.object(ma_mod, "get_market_now", return_value=tw_now), \
             patch.object(ma_mod, "get_effective_trading_date", return_value=date(2026, 8, 7)):
            assert MarketAnalyzer._resolve_overview_date(stub) == date(2026, 8, 7)

    def test_overview_date_reads_the_clock_once(self):
        """三次獨立讀鐘會在跨午夜／跨盤邊界自相矛盾——一次讀鐘，顯式傳給每個判定。

        與 PR #12 修的 `_augment_historical_with_realtime` 同形狀：牆鐘在兩次
        讀取之間跨過收盤邊界的話，phase 用舊時間、日期用新時間，決定就錯。
        """
        from datetime import date, datetime
        from zoneinfo import ZoneInfo

        import src.market_analyzer as ma_mod
        from src.core.trading_calendar import MarketPhase
        from src.market_analyzer import MarketAnalyzer

        stub = MagicMock(spec=MarketAnalyzer)
        stub.region = "tw"
        t0 = datetime(2026, 8, 10, 13, 29, 59, tzinfo=ZoneInfo("Asia/Taipei"))
        now_calls = []
        phase_times = []
        eff_times = []

        def fake_now(region, current_time=None):
            now_calls.append(current_time)
            return t0

        def fake_phase(market, current_time=None):
            phase_times.append(current_time)
            return MarketPhase.INTRADAY

        with patch.object(ma_mod, "get_market_now", side_effect=fake_now), \
             patch.object(ma_mod, "infer_market_phase", side_effect=fake_phase), \
             patch.object(ma_mod, "get_effective_trading_date",
                          side_effect=lambda m, current_time=None: eff_times.append(
                              current_time) or date(2026, 8, 7)):
            assert MarketAnalyzer._resolve_overview_date(stub) == t0.date()

        assert len(now_calls) == 1, f"时钟被读了 {len(now_calls)} 次"
        assert phase_times == [t0], "phase 判定必须用同一个时钟读数"
        assert eff_times == [], "盘后路径不该再问 effective trading date"

        # 開盤前分支：同一個時鐘讀數要一路傳到 effective_trading_date
        with patch.object(ma_mod, "get_market_now", side_effect=fake_now), \
             patch.object(ma_mod, "infer_market_phase",
                          side_effect=lambda m, current_time=None:
                              phase_times.append(current_time) or MarketPhase.PREMARKET), \
             patch.object(ma_mod, "get_effective_trading_date",
                          side_effect=lambda m, current_time=None: eff_times.append(
                              current_time) or date(2026, 8, 7)):
            assert MarketAnalyzer._resolve_overview_date(stub) == date(2026, 8, 7)
        assert eff_times[-1] == t0

    def test_missing_limit_counts_never_reach_prompt_or_payload_as_zero(self):
        """P1-1：本地寬度來源刻意不提供漲跌停家數（tw_breadth docstring），

        但 zh/en 兩份 prompt 區塊與結構化 payload 都無條件印 `limit_*_count`
        ⇒ LLM 寫出「漲跌停皆為0，顯示市場情緒溫和」這種虛構結論
        （reports/market_review_20260824.md 第 11、24 行實證）。
        """
        from src.market_analyzer import MarketAnalyzer

        ma = _analyzer("tw")
        overview = _overview(up_count=589, down_count=382, flat_count=104,
                             total_amount=9526.0)
        assert overview.limit_up_count == 0 and overview.limit_down_count == 0

        with patch.object(MarketAnalyzer, "_get_review_language", return_value="zh"), \
             patch.object(MarketAnalyzer, "_get_output_language", return_value="zh-TW"):
            prompt = MarketAnalyzer._build_review_prompt(ma, overview, [])

        assert "上涨: 589" in prompt or "上漲: 589" in prompt, "有讀數的家數要照常進 prompt"
        assert "涨停" not in prompt and "漲停" not in prompt, "缺資料的欄位不得以 0 進 prompt"

        with patch.object(MarketAnalyzer, "_get_output_language", return_value="zh-TW"), \
             patch.object(MarketAnalyzer, "_get_turnover_unit_label", return_value="亿"), \
             patch.object(MarketAnalyzer, "_describe_turnover", return_value="-"):
            payload = MarketAnalyzer.build_market_review_payload(
                ma, overview, [], "# 台股大盤複盤\n\n正文")

        breadth = payload["breadth"]
        assert breadth["up_count"] == 589
        assert "limit_up_count" not in breadth and "limit_down_count" not in breadth, \
            "缺資料要缺 key，不能給 0——0 是讀數，會順著 API/Web/分享圖流下去被當真"
        assert breadth["total_amount"] == 9526.0

    def test_missing_limit_counts_are_declared_as_a_data_limit(self):
        """光是「不出现」不够：LLM 分不出「缺资料」与「读数是 0」，所以要在资料边界
        里明说。prompt 顶端本来就有「未提供…不要编造或过度解读」那条纪律，这里是
        让它有东西可以对齐。
        """
        from src.market_analyzer import MarketAnalyzer

        ma = _analyzer("tw")
        overview = _overview(up_count=589, down_count=382, flat_count=104,
                             total_amount=9526.0)

        with patch.object(MarketAnalyzer, "_get_review_language", return_value="zh-TW"), \
             patch.object(MarketAnalyzer, "_get_output_language", return_value="zh-TW"):
            prompt = MarketAnalyzer._build_review_prompt(ma, overview, [])

        assert "本場次無漲跌停家數資料" in prompt
        assert "資料邊界" in prompt
        # 有讀數的兩欄不得被誤報成缺資料
        assert "無漲跌家數資料" not in prompt
        assert "無成交額彙總資料" not in prompt

    def test_english_branch_declares_the_same_data_limit(self):
        """en 与 zh 是两段各自独立的组装码，只测一边等于只修一边。"""
        from src.market_analyzer import MarketAnalyzer

        ma = _analyzer("tw")
        overview = _overview(up_count=589, down_count=382, flat_count=104,
                             total_amount=9526.0)

        with patch.object(MarketAnalyzer, "_get_review_language", return_value="en"), \
             patch.object(MarketAnalyzer, "_get_output_language", return_value="en"):
            prompt = MarketAnalyzer._build_review_prompt(ma, overview, [])

        assert "Limit-up/limit-down counts are unavailable" in prompt
        assert "Data Limits" in prompt
        # 缺资料的那一行不得同时以 0 的形式出现在 breadth 区块
        assert "Limit-up: 0" not in prompt
        # 有读数的两栏不得被误报成缺资料
        assert "Advance/decline counts are unavailable" not in prompt
        assert "Aggregate turnover is unavailable" not in prompt

    def test_available_limit_counts_produce_no_data_limit_line(self):
        """反向守門：把邊界寫成無條件輸出，這條會紅。"""
        from src.market_analyzer import MarketAnalyzer

        ma = _analyzer("tw")
        overview = _overview(up_count=342, down_count=671, flat_count=59,
                             limit_up_count=19, limit_down_count=10,
                             total_amount=7549.0)

        with patch.object(MarketAnalyzer, "_get_review_language", return_value="zh-TW"), \
             patch.object(MarketAnalyzer, "_get_output_language", return_value="zh-TW"):
            prompt = MarketAnalyzer._build_review_prompt(ma, overview, [])

        assert "本場次無漲跌停家數資料" not in prompt

    def test_institutional_only_stats_block_keeps_its_heading(self):
        """三大法人是唯一读数时，区块不能变成没有标头的裸 bullet。

        旧写法是 `stats_block += ...`，而 `stats_block` 只在 stats_lines 非空时才
        被赋成带标头的字串，于是「家数/涨跌停/成交额全缺、只有法人」会产出一串
        无主的 bullet 挂在 prompt 里。
        """
        from src.market_analyzer import MarketAnalyzer

        ma = _analyzer("tw")
        overview = _overview(institutional_net={
            "foreign_net": 276.0, "trust_net": 34.0,
            "dealer_net": 19.0, "total_net": 329.0})

        with patch.object(MarketAnalyzer, "_get_review_language", return_value="zh"), \
             patch.object(MarketAnalyzer, "_get_output_language", return_value="zh-TW"), \
             patch.object(MarketAnalyzer, "_get_turnover_unit_label", return_value="亿"):
            prompt = MarketAnalyzer._build_review_prompt(ma, overview, [])

        assert "三大法人买卖超" in prompt
        head = prompt.index("## 市场概况")
        assert head < prompt.index("三大法人买卖超"), "法人 bullet 必须挂在标头之下"

    def test_present_limit_counts_still_flow_through(self):
        """反向守門：真的有漲跌停讀數時（A股/twtazu_od 活著），閘門不能擋掉它。"""
        from src.market_analyzer import MarketAnalyzer

        ma = _analyzer("tw")
        overview = _overview(up_count=342, down_count=671, flat_count=59,
                             limit_up_count=19, limit_down_count=10,
                             total_amount=7549.0)

        with patch.object(MarketAnalyzer, "_get_review_language", return_value="zh"), \
             patch.object(MarketAnalyzer, "_get_output_language", return_value="zh-TW"):
            prompt = MarketAnalyzer._build_review_prompt(ma, overview, [])
        assert "涨停: 19 家" in prompt

        with patch.object(MarketAnalyzer, "_get_output_language", return_value="zh-TW"), \
             patch.object(MarketAnalyzer, "_get_turnover_unit_label", return_value="亿"), \
             patch.object(MarketAnalyzer, "_describe_turnover", return_value="-"):
            payload = MarketAnalyzer.build_market_review_payload(
                ma, overview, [], "# 台股大盤複盤\n\n正文")
        assert payload["breadth"]["limit_up_count"] == 19
        assert payload["breadth"]["limit_down_count"] == 10

    def test_prompt_index_lines_never_print_nan(self):
        """這是餵給 LLM 的那份，跟報告表格是兩個出口；之前只修了表格。"""
        from src.market_analyzer import MarketAnalyzer, MarketIndex

        ma = _analyzer("us")
        overview = _overview(indices=[
            MarketIndex(code="SPX", name="标普500指数", current=6400.0, change=30.0, change_pct=0.47),
            MarketIndex(code="IXIC", name="纳斯达克", current=float("nan"), change=0.0,
                        change_pct=float("nan")),
        ])
        with patch.object(MarketAnalyzer, "_get_review_language", return_value="zh-TW"), \
             patch.object(MarketAnalyzer, "_get_output_language", return_value="zh-TW"), \
             patch.object(MarketAnalyzer, "_get_strategy_prompt_block", return_value=""), \
             patch.object(MarketAnalyzer, "_get_index_hint", return_value="H"):
            prompt = MarketAnalyzer._build_review_prompt(ma, overview, [])

        assert "nan" not in prompt.lower()
        assert "标普500指数" in prompt, "有讀數的那檔不能一起被丟掉"

    def test_nan_mood_index_is_not_read_as_a_decline(self):
        """NaN 走完每個 `>` 比較都 False，會落到 else 被判成「明顯下跌」。"""
        from src.market_analyzer import MarketAnalyzer, MarketIndex

        ma = _analyzer("us")
        overview = _overview(indices=[
            MarketIndex(code="SPX", name="标普500指数", current=6400.0, change=0.0,
                        change_pct=float("nan")),
        ])
        with patch.object(MarketAnalyzer, "_get_template_review_language", return_value="zh-TW"), \
             patch.object(MarketAnalyzer, "_get_review_language", return_value="zh-TW"), \
             patch.object(MarketAnalyzer, "_get_turnover_unit_label", return_value="十億美元"):
            text = MarketAnalyzer._generate_template_review(ma, overview, [])

        assert "明顯下跌" not in text and "明显下跌" not in text, text[:400]

    @pytest.mark.parametrize("code,expected", [("AAPL-US", "AAPL"), ("AAPL.US", "AAPL")])
    def test_exchange_suffix_does_not_fall_through_to_shenzhen(self, code, expected):
        """`AAPL-US` 落到 A 股預設會變成 `AAPL-US.SZ`——查無資料、當成正常降級。"""
        from data_provider.yfinance_fetcher import YfinanceFetcher

        assert YfinanceFetcher()._convert_stock_code(code) == expected

    def test_search_service_recognises_the_hyphen_form(self):
        """判不出美股，新聞檢索整組走中文／境內路徑去查一檔美股。"""
        from src.search_service import SearchService

        assert SearchService._is_us_stock("BRK-B") is True
        assert SearchService._is_us_stock("BRK.B") is True

    def test_chinese_etf_names_still_match(self):
        """`\\b` 對 CJK 無效（CJK 也是 word char），會把港股中文 ETF 名整批漏掉。"""
        from src.search_service import SearchService

        assert SearchService._ETF_NAME_PATTERN.search("南方恒生科技ETF")
        assert not SearchService._ETF_NAME_PATTERN.search("NETFLIX")
        assert not SearchService._ETF_NAME_PATTERN.search("UNITEDHEALTH GROUP")

    def test_symbols_outside_the_official_list_keep_the_name_fallback(self):
        """官方清單外的真 ETF 若被當成權威的「不是 ETF」，就拿不到 ETF 式檢索。"""
        from src.data.stock_index_loader import get_us_asset_type
        from src.search_service import SearchService

        assert get_us_asset_type("BLCN") is None, "清單外的列不該給出權威答案"
        assert SearchService.is_index_or_etf("BLCN", "Siren Nasdaq NexGen Economy ETF") is True

    def test_safe_float_rejects_infinity(self):
        from data_provider.yfinance_fundamental_adapter import _safe_float

        assert _safe_float(float("inf")) is None
        assert _safe_float(float("-inf")) is None
        assert _safe_float(float("nan")) is None
        assert _safe_float(3.5) == 3.5

    def test_clearing_the_index_cache_also_clears_the_type_cache(self):
        import src.data.stock_index_loader as loader

        loader.get_us_asset_type("SPY")
        assert loader._US_ASSET_TYPE_CACHE is not None
        loader.clear_stock_index_cache()
        assert loader._US_ASSET_TYPE_CACHE is None

    def test_duration_baseline_accepts_every_configured_test_root(self):
        """重新產生時長基準表會含 market_data/tests 的條目，寫死單一前綴會開機即失敗。"""
        import json

        from scripts.ci_test_shard import TEST_ROOTS, load_durations

        payload = {"schema_version": 1,
                   "durations": {f"{root}/test_x.py": 1.0 for root in TEST_ROOTS}}
        path = pathlib.Path(tempfile.mkdtemp()) / "d.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert len(load_durations(path)) == len(TEST_ROOTS)


class TestTaiwanLetterSuffixedCodesSurviveTheUnsupportedGate:
    """`00631L.TW` 这类代码必须走完整条台股路径，而不是在 parser 就被判 unsupported。

    上游 #2267 给 `DataFetcherManager.get_stock_data` 加了一道硬守门：
    `parse_analysis_target` 判 UNSUPPORTED 就 `raise DataFetchError`，**在 fetcher 清单
    建起来之前**。fork main 上没有这道守门（`git show 11116673:data_provider/base.py`
    完全没有 `ParseStatus.UNSUPPORTED`），所以合并前这些代码是能跑的。

    台股带尾字母的代码是真实存在且常用的：槓桿 `00631L`、反向 `00632R`、债券 ETF
    `00679B`、特别股 `2887A`。四条路径都得认它，缺一条就会以不同形式失效。
    """

    CODES = ("00631L.TW", "00632R.TW", "00679B.TW", "2887A.TW", "00675L.TWO")

    def test_parse_analysis_target_classifies_them_as_stock(self):
        from src.services.stock_list_parser import parse_analysis_target

        for code in self.CODES:
            target = parse_analysis_target(code)
            assert target.asset_type == "stock", (
                code, target.asset_type, target.unsupported_reason
            )

    def test_suffix_market_resolves_to_tw(self):
        from src.services.market_symbol_utils import get_suffix_market

        for code in self.CODES:
            assert get_suffix_market(code) == "tw", code

    def test_yfinance_recognises_them_as_tw_suffix_stocks(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher

        for code in self.CODES:
            assert YfinanceFetcher._is_tw_suffix_stock(code) is True, code
            assert YfinanceFetcher._is_yahoo_suffix_stock(code) is True, code

    def test_normalization_keeps_the_letter_and_skips_hk_zfill(self):
        """放行字母尾之後，base 必须原样带着字母出来，且不得掉进 HK 的 `zfill(5)`。"""
        from data_provider.base import normalize_stock_code
        from src.services.stock_code_utils import (
            _normalize_explicit_exchange_parts,
            _split_explicit_exchange,
        )

        for code in self.CODES:
            assert normalize_stock_code(code) == code.upper(), code
            base = _normalize_explicit_exchange_parts(_split_explicit_exchange(code.upper()))
            assert base == code.upper().rsplit(".", 1)[0], (code, base)
            assert not base.startswith("0000"), (code, base)  # HK zfill(5) 的指纹

    def test_a_letter_base_is_still_not_a_free_pass(self):
        """只放行「4~6 位数字 + 至多一个尾字母」，不是放行任意 base。"""
        from src.services.market_symbol_utils import get_suffix_market

        for bad in ("ABCDE.TW", "00631LL.TW", "631L.TWO", "1234567L.TW", "L0063.TW"):
            assert get_suffix_market(bad) is None, bad

    def test_unicode_letters_and_digits_do_not_sneak_through(self):
        """**只认 ASCII。** `str.isalpha()` 与 `str.isdigit()` 都是 Unicode-aware：
        `'甲'.isalpha()`、`'Ｌ'.isalpha()`、`'００６３１'.isdigit()`、`'٠٠٦٣١'.isdigit()`
        全为 True。用它们判代码，`2330甲.TW` 会被判成合法台股一路穿过 unsupported
        守门、带着无效字元送进 yfinance；抓取失败时 pipeline 刻意 fail-open 继续，
        於是产出一份静默缺资料的报告，而不是一个明确的拒收。
        """
        from src.services.market_symbol_utils import get_suffix_market
        from src.services.stock_list_parser import parse_analysis_target

        for bad in (
            "00631Ｌ.TW",    # 全形字母
            "2330甲.TW",     # 漢字
            "2330α.TW",      # 希臘字母
            "００６３１.TW",    # 全形數字
            "٠٠٦٣١.TW",      # 阿拉伯數字
            "７２０３.T",       # jp 同樣收緊
        ):
            assert get_suffix_market(bad) is None, bad
            assert parse_analysis_target(bad).asset_type == "unsupported", bad
