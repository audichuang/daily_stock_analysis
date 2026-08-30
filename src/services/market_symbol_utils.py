# -*- coding: utf-8 -*-
"""Shared market-symbol helpers for suffix-only offshore markets.

Keep this module dependency-light so it can be used by data providers, market
context, trading calendars, stock-index loading, and API input normalization
without introducing import cycles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SuffixMarketSpec:
    """A suffix-only Yahoo Finance market rule."""

    market: str
    suffixes: tuple[str, ...]
    digit_lengths: tuple[int, ...]


_SUFFIX_MARKET_SPECS: tuple[SuffixMarketSpec, ...] = (
    SuffixMarketSpec("jp", ("T",), (4, 5)),
    SuffixMarketSpec("kr", ("KS", "KQ"), (6,)),
    # Taiwan support mirrors the same suffix-only pattern; keep it here so the
    # shared helpers stay complete for all yfinance-only offshore markets.
    SuffixMarketSpec("tw", ("TW", "TWO"), (4, 5, 6)),
)

_MARKET_TO_SPEC = {spec.market: spec for spec in _SUFFIX_MARKET_SPECS}
_SUFFIX_TO_SPEC = {
    suffix: spec
    for spec in _SUFFIX_MARKET_SPECS
    for suffix in spec.suffixes
}


def strip_optional_tw_letter(base: str) -> str:
    """Drop one trailing letter from a Taiwan base code, else return it unchanged.

    Taiwan codes carry an optional single trailing uppercase letter and the letter is
    load-bearing, not noise: leveraged / inverse ETFs (``00631L`` 元大台灣50正2,
    ``00632R`` 元大台灣50反1), bond ETFs (``00679B``) and preferred shares (``2887A``)
    all use it. The other suffix-only markets here (jp / kr) are digits-only, so this
    is applied to ``tw`` / ``.TW`` / ``.TWO`` only.

    Callers strip the letter and then apply their own digit-length rule, so the length
    knowledge stays in one place (``SuffixMarketSpec.digit_lengths`` / the caller's
    ``digit_lens``) instead of being duplicated into a regex here.

    Widening this was deliberated once before and deferred — see the "已知未覆蓋" note
    this replaces in ``src/services/name_to_code_resolver.py``. Upstream #2267 then
    added a hard ``ParseStatus.UNSUPPORTED`` gate in ``DataFetcherManager.get_stock_data``
    that raises before any fetcher runs, which turned the dormant gap into a Taiwan ETF
    outage, so the trade-off flipped.
    """
    text = (base or "").strip().upper()
    # **必须逐字比对 ASCII 范围，不能用 `isalpha()`／`isdigit()`。** 两者都是
    # Unicode-aware：`'甲'.isalpha()` 与 `'Ｌ'.isalpha()` 都为 True，`'１'.isdigit()`
    # 亦然，於是 `2330甲.TW` / `00631Ｌ.TW` 会被判成合法台股代码，一路穿过
    # `parse_analysis_target` 与 unsupported 守门，带着无效字元送进 yfinance；
    # 抓取失败时 pipeline 刻意 fail-open 继续跑，结果是一份静默缺资料的报告，
    # 而不是一个明确的拒收。
    if len(text) > 1 and "A" <= text[-1] <= "Z" and text[:-1].isascii() and text[:-1].isdigit():
        return text[:-1]
    return text


def split_suffix_symbol(stock_code: str) -> tuple[str, str] | None:
    """Return ``(base, suffix)`` for dotted symbols, upper-cased and stripped."""

    code = (stock_code or "").strip().upper()
    if "." not in code:
        return None
    base, suffix = code.rsplit(".", 1)
    if not base or not suffix:
        return None
    return base, suffix


def get_suffix_market(stock_code: str) -> Optional[str]:
    """Return jp/kr/tw for supported suffix-only Yahoo symbols, else None."""

    parts = split_suffix_symbol(stock_code)
    if parts is None:
        return None
    base, suffix = parts
    spec = _SUFFIX_TO_SPEC.get(suffix)
    if spec is None:
        return None
    if spec.market == "tw":
        base = strip_optional_tw_letter(base)
    # `.isascii()` 是必要的：`str.isdigit()` 是 Unicode-aware，`'００６３１'.isdigit()`
    # 与 `'٠٠٦٣١'.isdigit()` 都为 True，於是全形／阿拉伯数字会被当成合法代码送进
    # yfinance。这一层对 jp/kr 同样收紧，方向一致（`７２０３.T` 也不该是合法日股代码）。
    if not (base.isascii() and base.isdigit() and len(base) in spec.digit_lengths):
        return None
    return spec.market


def is_suffix_market_symbol(stock_code: str, market: Optional[str] = None) -> bool:
    """Return whether a stock code is a supported suffix-only Yahoo symbol."""

    detected = get_suffix_market(stock_code)
    if market is None:
        return detected is not None
    return detected == (market or "").strip().lower()


def is_jp_suffix_symbol(stock_code: str) -> bool:
    return is_suffix_market_symbol(stock_code, "jp")


def is_kr_suffix_symbol(stock_code: str) -> bool:
    return is_suffix_market_symbol(stock_code, "kr")


def is_tw_suffix_symbol(stock_code: str) -> bool:
    return is_suffix_market_symbol(stock_code, "tw")


def normalize_suffix_market_symbol(stock_code: str) -> Optional[str]:
    """Normalize supported suffix-only symbols to upper-case Yahoo form."""

    parts = split_suffix_symbol(stock_code)
    if parts is None:
        return None
    base, suffix = parts
    if get_suffix_market(f"{base}.{suffix}") is None:
        return None
    return f"{base}.{suffix}"


def suffix_base_lookup_allowed(canonical_code: str) -> bool:
    """Return True when a suffix-market code may be resolved from its bare base.

    JP/KR intentionally allow stock-index-backed bare-code lookup to support the
    existing MVP behavior. TW remains strict suffix-only for now because its
    follow-up index work is not part of this issue.
    """

    return get_suffix_market(canonical_code) in {"jp", "kr"}


def market_suffixes(market: str) -> tuple[str, ...]:
    spec = _MARKET_TO_SPEC.get((market or "").strip().lower())
    return spec.suffixes if spec else ()
