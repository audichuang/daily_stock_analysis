# -*- coding: utf-8 -*-
"""美股路徑的守門測試。

這個 fork 長期只跑台股，美股路徑上累積了一批**不報錯、只給錯數字**的問題：
代碼轉換掉一種寫法、市場判定 fallback 到 A 股、幣別寫死人民幣、prompt 要求模型
分析一個它一格資料都沒有的欄位。共同形狀是「報告照出、測試照綠」，所以這裡的
每一項都斷言**可觀察的輸出**，而不是內部狀態。

每一項都做過 mutation 檢查：把修法改回舊寫法必須立刻紅。
"""

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
    ])
    def test_operating_companies_are_not_flagged_as_etf(self, code, name):
        """被誤判成 ETF 的個股會**整組失去公司風險／財報／競爭檢索**，只剩指數式查詢。"""
        from src.search_service import SearchService

        assert SearchService.is_index_or_etf(code, name) is False


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

        spy.assert_called_once_with("us")
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
