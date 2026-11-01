# -*- coding: utf-8 -*-
"""Aggregate existing stock research capabilities behind one partial-data contract."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from data_provider.base import canonical_stock_code
from src.repositories.portfolio_repo import PortfolioRepository
from src.core.trading_calendar import MarketPhase, infer_market_phase, latest_opened_session
from src.services.alert_service import AlertService
from src.services.event_outlook import extract_event_outlook
from src.services.history_service import HistoryService
from src.services.intelligence_service import IntelligenceService
from src.services.market_symbol_utils import get_suffix_market
from src.services.research_artifact_service import artifact_input_from_detail, build_research_artifact
from src.services.stock_code_utils import resolve_daily_stock_identity
from src.services.stock_service import StockService

logger = logging.getLogger(__name__)

_BLOCK_NAMES = ("quote", "history", "research", "intelligence", "portfolio", "monitors")


class InvalidStockProfileCode(ValueError):
    """Raised when a stock profile request has no unambiguous shared identity."""


class StockProfileService:
    """Build a stock profile while isolating optional-source failures by block."""

    def __init__(
        self,
        *,
        stock_service: Optional[StockService] = None,
        history_service: Optional[HistoryService] = None,
        intelligence_service: Optional[IntelligenceService] = None,
        portfolio_repository: Optional[PortfolioRepository] = None,
        alert_service: Optional[AlertService] = None,
    ):
        self.stock_service = stock_service
        self.history_service = history_service
        self.intelligence_service = intelligence_service
        self.portfolio_repository = portfolio_repository
        self.alert_service = alert_service

    def get_profile(self, requested_code: str, *, history_days: int = 60) -> Dict[str, Any]:
        canonical_code = self.canonicalize_code(requested_code)
        market = self.market_for_code(canonical_code)
        blocks = {
            "quote": self._quote_block(canonical_code),
            "history": self._history_block(canonical_code, history_days=history_days),
            "research": self._research_block(canonical_code, market=market),
            "intelligence": self._intelligence_block(canonical_code, market=market),
            "portfolio": self._portfolio_block(canonical_code, market=market),
            "monitors": self._monitor_block(canonical_code, market=market),
        }
        blocks["history"] = self._with_provisional_bar(blocks["history"], blocks["quote"], market=market)
        blocks["quote"] = self._with_official_session_volume(blocks["quote"], blocks["history"], market=market)
        return {
            "requested_code": str(requested_code).strip(),
            "canonical_code": canonical_code,
            "market": market,
            "as_of": datetime.now().astimezone().isoformat(),
            **blocks,
            "evidence_quality": self._evidence_quality(blocks),
            # 追加區塊不進 _BLOCK_NAMES：缺資料回 null，不改變既有的品質判定。
            "position": self._position_block(canonical_code, market=market, quote=blocks["quote"])
            if blocks["portfolio"]["data"].get("held")
            else None,
            "chips": self._chips_block(canonical_code) if market == "tw" else None,
            "news": self._news_block(blocks["research"]),
        }

    @staticmethod
    def canonicalize_code(value: str) -> str:
        raw = str(value or "").strip()
        identity = resolve_daily_stock_identity(raw)
        if identity is None:
            raise InvalidStockProfileCode("stock code has no unambiguous market identity")
        normalized = canonical_stock_code(identity.refill_code or identity.normalized_code)
        if normalized.isdigit() and len(normalized) == 5:
            return f"HK{normalized.zfill(5)}"
        return normalized.upper()

    @staticmethod
    def market_for_code(canonical_code: str) -> str:
        if canonical_code.startswith("HK"):
            return "hk"
        suffix_market = get_suffix_market(canonical_code)
        if suffix_market:
            return suffix_market
        if canonical_code.isdigit() and len(canonical_code) == 6:
            return "cn"
        return "us"

    def _quote_block(self, code: str) -> Dict[str, Any]:
        try:
            quote = self._stock_service().get_realtime_quote(code)
        except Exception:
            quote = None
        if not quote:
            return self._unavailable("quote_unavailable", data=None)
        return {"status": "fresh", "data": quote, "limitations": []}

    def _history_block(self, code: str, *, history_days: int) -> Dict[str, Any]:
        try:
            result = self._stock_service().get_history_data(code, period="daily", days=history_days)
            rows = list(result.get("data") or [])
        except Exception:
            rows = []
        if not rows:
            return {
                "status": "unavailable",
                "period": "daily",
                "data": [],
                "limitations": ["history_unavailable"],
            }
        return {"status": "fresh", "period": "daily", "data": rows, "limitations": []}

    @staticmethod
    def _with_provisional_bar(history: Dict[str, Any], quote: Dict[str, Any], *, market: str) -> Dict[str, Any]:
        """報價屬於比日 K 最後一根更新的交易日時，用報價補一根暫定 K（provisional=True）。

        踩過：yfinance 在 INTC 2026-10-30 大跌當天回 OHLC 全 NaN 的日 K，被丟掉後圖表停在前一天，
        和報價差了 28%。交易日由市場當地時間判斷（美股收盤後的 UTC 已是隔天），過期報價不補。
        """
        rows = history.get("data") or []
        data = quote.get("data") or {}
        price = data.get("current_price")
        if not rows or not price or data.get("is_stale") or not data.get("as_of"):
            return history
        try:
            as_of = datetime.fromisoformat(str(data["as_of"]))
        except ValueError:
            return history
        session = latest_opened_session(market, as_of)
        if session is None or session.isoformat() <= str(rows[-1].get("date")):
            return history
        prev_close = rows[-1].get("close")
        bar = {
            "date": session.isoformat(),
            "open": data.get("open") or price,
            "high": max(v for v in (data.get("high"), price) if v),
            "low": min(v for v in (data.get("low"), price) if v),
            "close": price,
            "volume": data.get("volume"),
            "amount": data.get("amount"),
            "change_percent": (price / prev_close - 1) * 100 if prev_close else None,
            "provisional": True,
        }
        return {**history, "data": [*rows, bar]}

    @staticmethod
    def _with_official_session_volume(
        quote: Dict[str, Any],
        history: Dict[str, Any],
        *,
        market: str,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """台股收盤後，同一場次的日 K 已入庫時，頁首的量與額改用日 K，同頁只留一個口徑。

        盤中日 K 不是完整一天，維持即時值。只有這條路徑（profile）會對齊，單獨打 /quote 不變。
        """
        data = quote.get("data") or {}
        rows = history.get("data") or []
        if market != "tw" or not rows or not data.get("as_of") or rows[-1].get("provisional"):
            return quote
        try:
            as_of = datetime.fromisoformat(str(data["as_of"]))
        except ValueError:
            return quote
        session = latest_opened_session(market, as_of)
        phase = infer_market_phase(market, now or datetime.now().astimezone())
        if (
            session is None
            or session.isoformat() != str(rows[-1].get("date"))
            or phase not in {MarketPhase.POSTMARKET, MarketPhase.NON_TRADING}
        ):
            return quote
        merged = dict(data)
        for key in ("volume", "amount"):
            if rows[-1].get(key):
                merged[key] = rows[-1][key]
        return {**quote, "data": merged}

    def _position_block(self, code: str, *, market: str, quote: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """從帳本重放算持股（唯讀、不抓即時價、不寫快照）；損益用頁首同一個即時價。"""
        try:
            from src.services.portfolio_service import PortfolioService

            snapshot = PortfolioService(repo=self._portfolio_repository()).get_portfolio_snapshot(
                include_realtime=False,
                read_only=True,
            )
            profile_identity = resolve_daily_stock_identity(code, market_hint=market)
            matched = []
            mv_aggregate = 0.0
            for account in snapshot.get("accounts") or []:
                account_mv = float(account.get("total_market_value") or 0.0)
                account_aggregate = account.get("total_market_value_aggregate")
                for position in account.get("positions") or []:
                    pos_market = str(position.get("market") or "").strip().lower()
                    identity = resolve_daily_stock_identity(position.get("symbol"), market_hint=pos_market)
                    if (
                        identity is None
                        or identity.market != market
                        or not self._same_profile_identity(identity, profile_identity)
                    ):
                        continue
                    matched.append(position)
                    if mv_aggregate is not None:
                        if account_aggregate is None or account_mv <= 0:
                            mv_aggregate = None
                        else:
                            mv_aggregate += float(position.get("market_value_base") or 0.0) * (
                                float(account_aggregate) / account_mv
                            )
            if not matched:
                return None
            quantity = sum(float(p.get("quantity") or 0.0) for p in matched)
            if quantity <= 0:
                return None
            currencies = {str(p.get("currency") or "") for p in matched}
            single_currency = currencies.pop() if len(currencies) == 1 else None
            avg_cost = (
                sum(float(p.get("total_cost") or 0.0) for p in matched) / quantity if single_currency else None
            )
            quote_price = (quote.get("data") or {}).get("current_price")
            available = [p for p in matched if p.get("price_available")]
            last_price = quote_price or (float(available[0]["last_price"]) if available else None)
            has_pnl = bool(last_price and avg_cost is not None)
            total_mv = float(snapshot.get("total_market_value") or 0.0)
            weight = (
                round(mv_aggregate / total_mv * 100, 2)
                if mv_aggregate is not None and total_mv > 0 and not snapshot.get("fx_missing") and available
                else None
            )
            return {
                "quantity": quantity,
                "avg_cost": round(avg_cost, 4) if avg_cost is not None else None,
                "currency": single_currency or None,
                "last_price": last_price,
                "market_value": round(last_price * quantity, 2) if last_price and single_currency else None,
                "unrealized_pnl": round((last_price - avg_cost) * quantity, 2) if has_pnl else None,
                "unrealized_pnl_pct": (
                    round((last_price / avg_cost - 1) * 100, 2) if has_pnl and avg_cost > 0 else None
                ),
                "weight_pct": weight,
                "account_count": len(matched),
            }
        except Exception as exc:
            logger.warning("個股 profile 持股區塊失敗 %s: %s", code, type(exc).__name__)
            return None

    @staticmethod
    def _chips_block(code: str) -> Optional[Dict[str, Any]]:
        """本地 DB 的法人與融資融券（各自的最新場次，日期分開給）。兩塊都沒有才回 None。"""
        try:
            from data_provider.tw_margin_trend import compute_margin_trend
            from market_data import market_repo
            from market_data.db import get_engine

            engine = get_engine(statement_timeout_ms=3000)
            stock_id = code.split(".", 1)[0]
            start = (datetime.now().astimezone().date() - timedelta(days=60)).isoformat()
            institutional = market_repo.institutional(stock_id, start=start, engine=engine)
            margin_rows = market_repo.margin(stock_id, start=start, engine=engine).to_dict("records")
        except Exception as exc:
            logger.warning("個股 profile 籌碼區塊失敗 %s: %s", code, type(exc).__name__)
            return None
        chips: Dict[str, Any] = {}
        if not institutional.empty:
            latest = institutional.iloc[-1]
            chips["institutional_date"] = str(latest["date"])[:10]
            for key in ("foreign_net", "trust_net", "dealer_net", "total_net"):
                value = latest.get(key)
                chips[key] = None if value is None or value != value else float(value)
        margin = compute_margin_trend(margin_rows)
        if margin:
            chips["margin_date"] = margin.get("as_of")
            for key in ("margin_balance", "margin_chg_5", "margin_chg_20", "short_balance", "short_margin_ratio"):
                chips[key] = margin.get(key)
        return chips or None

    def _news_block(self, research: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """最新一份報告讀過的新聞，與報告頁同一條查詢。"""
        latest = ((research.get("data") or {}).get("latest_report")) or {}
        record_id = latest.get("id")
        if record_id is None:
            return None
        try:
            items = self._history_service().resolve_and_get_news(str(record_id), limit=10, analysis_only=True)
        except Exception:
            return None
        if not isinstance(items, list):
            return None
        return [
            {key: item.get(key) for key in ("title", "url", "source", "published_date")}
            for item in items
        ]

    def _research_block(self, code: str, *, market: str) -> Dict[str, Any]:
        empty_data = {"latest_report": None, "recent_reports": [], "structured_report": None, "event_outlook": None}
        try:
            query_options: Dict[str, Any] = {
                "stock_code": code,
                "page": 1,
                "limit": 5,
                "market_hint": market,
            }
            if market in {"jp", "kr", "tw"}:
                query_options["include_ambiguous_numeric_aliases"] = False
            result = self._history_service().get_history_list(**query_options)
            reports = list(result.get("items") or [])
        except Exception:
            return self._unavailable("report_list_unavailable", data=empty_data)
        if not reports:
            return self._unavailable("no_reports", data=empty_data)

        latest = reports[0]
        record_id = latest.get("id")
        if record_id is None:
            return {
                "status": "partial",
                "data": {
                    "latest_report": latest,
                    "recent_reports": reports,
                    "structured_report": None,
                },
                "limitations": ["latest_report_id_unavailable"],
            }
        try:
            detail = self._history_service().get_history_detail_by_id(int(record_id))
        except Exception:
            detail = None
        if not detail:
            return {
                "status": "partial",
                "data": {
                    "latest_report": latest,
                    "recent_reports": reports,
                    "structured_report": None,
                },
                "limitations": ["latest_report_detail_unavailable"],
            }
        try:
            artifact = build_research_artifact(self._artifact_input(detail))
        except Exception:
            artifact = None
        return {
            "status": "fresh" if artifact else "partial",
            "data": {
                "latest_report": latest,
                "recent_reports": reports,
                "structured_report": artifact,
                "event_outlook": extract_event_outlook(detail.get("raw_result")),
            },
            "limitations": [] if artifact else ["structured_report_unavailable"],
        }

    def _intelligence_block(self, code: str, *, market: str) -> Dict[str, Any]:
        items_by_id: Dict[Any, Dict[str, Any]] = {}
        successful_queries = 0
        failed_queries = 0
        markets = [market] if market == "global" else [market, "global"]
        aliases = self._code_aliases(code, market_hint=market)
        safe_global_aliases = set(
            self._code_aliases(
                code,
                market_hint=market,
                include_ambiguous_numeric=False,
            )
        )
        for alias in aliases:
            for query_market in markets:
                if query_market == "global" and alias not in safe_global_aliases:
                    continue
                try:
                    result = self._intelligence_service().list_items(
                        scope_type="symbol",
                        scope_value=alias,
                        market=query_market,
                        page=1,
                        page_size=10,
                    )
                    successful_queries += 1
                except Exception:
                    failed_queries += 1
                    continue
                for item in result.get("items") or []:
                    key = item.get("id")
                    if key is None:
                        key = (item.get("source_type"), item.get("url"), item.get("title"))
                    items_by_id.setdefault(key, item)
        if successful_queries == 0:
            return self._unavailable("intelligence_query_failed", items=[])
        items = sorted(
            items_by_id.values(),
            key=lambda item: (
                str(item.get("published_at") or item.get("fetched_at") or item.get("created_at") or ""),
                int(item.get("id") or 0),
            ),
            reverse=True,
        )[:10]
        if not items:
            if failed_queries:
                return {
                    "status": "partial",
                    "items": [],
                    "limitations": ["intelligence_alias_query_partial"],
                }
            return self._unavailable("no_symbol_intelligence", items=[])
        return {
            "status": "partial" if failed_queries else "fresh",
            "items": items,
            "limitations": ["intelligence_alias_query_partial"] if failed_queries else [],
        }

    def _portfolio_block(self, code: str, *, market: str) -> Dict[str, Any]:
        try:
            profile_identity = resolve_daily_stock_identity(code, market_hint=market)
            identities = self._portfolio_repository().list_cached_position_identities()
            matches = []
            for position_market, symbol in identities:
                normalized_market = str(position_market or "").strip().lower()
                identity = resolve_daily_stock_identity(symbol, market_hint=normalized_market)
                if identity is None or identity.market != normalized_market or identity.market != market:
                    continue
                if self._same_profile_identity(identity, profile_identity):
                    matches.append(normalized_market)
        except Exception:
            return self._unavailable(
                "portfolio_relation_unavailable",
                data={"held": False, "matched_markets": []},
            )
        return {
            "status": "partial",
            "data": {"held": bool(matches), "matched_markets": list(dict.fromkeys(matches))},
            "limitations": ["cached_positions_only"],
        }

    @staticmethod
    def _same_profile_identity(position_identity: Any, profile_identity: Any) -> bool:
        if profile_identity is None:
            return False
        position_codes = {
            str(position_identity.normalized_code or "").strip().upper(),
            str(position_identity.refill_code or "").strip().upper(),
        } - {""}
        profile_codes = {
            str(profile_identity.normalized_code or "").strip().upper(),
            str(profile_identity.refill_code or "").strip().upper(),
        } - {""}
        if position_codes & profile_codes:
            return True
        if position_identity.market in {"kr", "tw"} and not position_identity.refill_code:
            profile_base = str(profile_identity.normalized_code or "").split(".", 1)[0]
            return position_identity.normalized_code == profile_base
        return False

    def _monitor_block(self, code: str, *, market: str) -> Dict[str, Any]:
        rules_by_id: Dict[Any, Dict[str, Any]] = {}
        successful_queries = 0
        failed_queries = 0
        for alias in self._code_aliases(
            code,
            market_hint=market,
            include_ambiguous_numeric=False,
        ):
            page = 1
            scanned = 0
            try:
                while True:
                    result = self._alert_service().list_rules(
                        target_scope="single_symbol",
                        target=alias,
                        page=page,
                        page_size=100,
                    )
                    successful_queries += 1
                    rules = list(result.get("items") or [])
                    for rule in rules:
                        key = rule.get("id")
                        if key is None:
                            key = (alias, rule.get("name"), rule.get("alert_type"))
                        rules_by_id.setdefault(key, rule)
                    scanned += len(rules)
                    total = int(result.get("total") or 0)
                    if scanned >= total or not rules:
                        break
                    page += 1
            except Exception:
                failed_queries += 1
        if successful_queries == 0:
            return self._unavailable(
                "monitor_query_failed",
                data={"total_rule_count": 0, "enabled_rule_count": 0, "rule_ids": []},
            )
        rules = list(rules_by_id.values())
        return {
            "status": "partial" if failed_queries else "fresh",
            "data": {
                "total_rule_count": len(rules),
                "enabled_rule_count": sum(1 for rule in rules if rule.get("enabled")),
                "rule_ids": [int(rule["id"]) for rule in rules if rule.get("id") is not None],
            },
            "limitations": ["monitor_alias_query_partial"] if failed_queries else [],
        }

    @staticmethod
    def _code_aliases(
        code: str,
        *,
        market_hint: Optional[str] = None,
        include_ambiguous_numeric: bool = True,
    ) -> List[str]:
        market = str(market_hint or StockProfileService.market_for_code(code)).strip().lower()
        identity = resolve_daily_stock_identity(code, market_hint=market)
        candidates = list(identity.code_candidates) if identity is not None and identity.market == market else [code]
        if include_ambiguous_numeric and market in {"jp", "kr", "tw"} and "." in code:
            numeric_base = code.split(".", 1)[0]
            if numeric_base.isdigit():
                candidates.append(numeric_base)
        aliases: List[str] = []
        seen_aliases = set()
        for candidate in candidates or [code]:
            candidate_text = str(candidate).strip()
            if not include_ambiguous_numeric and candidate_text.isdigit():
                unhinted_identity = resolve_daily_stock_identity(candidate_text)
                same_market = unhinted_identity is not None and unhinted_identity.market == market
                legacy_short_hk = (
                    market == "hk"
                    and len(candidate_text) <= 3
                    and (
                        hinted_identity := resolve_daily_stock_identity(
                            candidate_text,
                            market_hint="hk",
                        )
                    ) is not None
                    and hinted_identity.market == "hk"
                )
                if not same_market and not legacy_short_hk:
                    continue
            alias_key = candidate_text.casefold()
            if candidate_text and alias_key not in seen_aliases:
                seen_aliases.add(alias_key)
                aliases.append(candidate_text)
        return aliases

    def _artifact_input(self, detail: Dict[str, Any]) -> Dict[str, Any]:
        try:
            persisted_fundamental = self._history_service().get_latest_fundamental_snapshot(
                query_id=str(detail.get("query_id") or "").strip(),
                stock_code=str(
                    detail.get("storage_stock_code") or detail.get("stock_code") or ""
                ).strip(),
            )
        except Exception:
            persisted_fundamental = None
        return artifact_input_from_detail(detail, persisted_fundamental=persisted_fundamental)

    def _stock_service(self) -> StockService:
        if self.stock_service is None:
            self.stock_service = StockService()
        return self.stock_service

    def _history_service(self) -> HistoryService:
        if self.history_service is None:
            self.history_service = HistoryService()
        return self.history_service

    def _intelligence_service(self) -> IntelligenceService:
        if self.intelligence_service is None:
            self.intelligence_service = IntelligenceService()
        return self.intelligence_service

    def _portfolio_repository(self) -> PortfolioRepository:
        if self.portfolio_repository is None:
            self.portfolio_repository = PortfolioRepository()
        return self.portfolio_repository

    def _alert_service(self) -> AlertService:
        if self.alert_service is None:
            self.alert_service = AlertService()
        return self.alert_service

    @staticmethod
    def _unavailable(limitation: str, **payload: Any) -> Dict[str, Any]:
        return {"status": "unavailable", **payload, "limitations": [limitation]}

    @staticmethod
    def _evidence_quality(blocks: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        statuses = {name: str(blocks[name]["status"]) for name in _BLOCK_NAMES}
        status_values = set(statuses.values())
        if status_values == {"fresh"}:
            overall = "fresh"
        elif status_values == {"unavailable"}:
            overall = "unavailable"
        else:
            overall = "partial"
        limitations = []
        for name in _BLOCK_NAMES:
            limitations.extend(str(item) for item in blocks[name].get("limitations") or [])
        return {
            "status": overall,
            "blocks": statuses,
            "limitations": list(dict.fromkeys(limitations)),
        }
