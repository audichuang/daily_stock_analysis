"""Taiwan stock trading cash flows.

Broker commission is charged on both buys and sells. Stock transaction tax is
charged only on a sale. The NHI supplementary premium is deliberately separate:
it applies to an eligible dividend payment, not to sale proceeds, and cannot be
inferred from an adjusted-price return.

The functions keep fractional TWD values because broker-side rounding rules can
vary. Callers that know their broker's invoice rounding can round the final cash
flow without changing the tax base used here.

`TRADING_DAYS_PER_YEAR` lives here too so every script annualises against the same
calendar — it is a Taiwan market convention, like the fee and tax rates above it.
"""

from __future__ import annotations

from datetime import date, datetime

from src.services.market_symbol_utils import is_tw_suffix_symbol, split_suffix_symbol

# 台股年均交易日。**所有腳本的年化都必須用同一個數字**，否則同一條淨值曲線在兩支腳本裡
# 會印出不同的 CAGR 與 Sharpe，而讀者無從對帳。踩過：`backtest_screen` 用美股慣例 252、
# `portfolio_walkforward` 用 245，於是同一段 0050 買進持有被報成 +29.37% 與 +28.44%
# （差 0.93pp，純粹來自 denominator）。實測 2020-01-02~2026-07-24 是 242.8 交易日/年。
# 超額報酬幾乎不受影響（兩臂共用同一個 years），但絕對 CAGR 與 Sharpe 會被高估。
TRADING_DAYS_PER_YEAR = 245

BROKER_FEE_RATE = 0.001425
MINIMUM_BROKER_FEE = 20.0
STOCK_TRANSACTION_TAX_RATE = 0.003
# ETF（含 0050）的證交稅是賣方 0.1%，不是股票的 0.3%。基準若沿用股票稅率會**高估**
# 0050 的成本，而本策略的結論正是「風險調整後輸給 0050」——偏誤方向對策略有利，必須修。
ETF_TRANSACTION_TAX_RATE = 0.001
DEFAULT_SLIPPAGE_RATE = 0.0015

# 證券交易稅條例第 2-1 條（2026-10-26 核對）：延長年限的草案尚未生效。
# https://law-out.mof.gov.tw/LawContent.aspx?id=FL006079
BOND_ETF_TAX_EXEMPT_START = date(2017, 1, 1)
BOND_ETF_TAX_EXEMPT_END = date(2026, 12, 31)

NHI_SUPPLEMENTARY_PREMIUM_RATE = 0.0211
NHI_DIVIDEND_PAYMENT_THRESHOLD = 20_000.0
NHI_DIVIDEND_PAYMENT_CAP = 10_000_000.0


def tw_transaction_tax_rate(stock_id: str, sell_date: date) -> float:
    """台股賣方稅率；接受已知台股資料的裸 ID 或合法 .TW／.TWO 代碼。

    免稅只適用一般債券 ETF（00 開頭、B 結尾），L／R 槓桿與反向商品仍課稅。
    日期必須由成交端傳入，不以執行回測時的牆鐘推斷歷史稅率。
    """
    code = str(stock_id).strip().upper()
    if not is_tw_suffix_symbol(code if "." in code else f"{code}.TW"):
        raise ValueError("expected a Taiwan stock ID or .TW/.TWO symbol")
    parts = split_suffix_symbol(code)
    base = parts[0] if parts else code
    day = sell_date.date() if isinstance(sell_date, datetime) else sell_date
    if not isinstance(day, date):
        raise ValueError("sell_date must be a date")
    if not base.startswith("00"):
        return STOCK_TRANSACTION_TAX_RATE
    if base.endswith("B") and BOND_ETF_TAX_EXEMPT_START <= day <= BOND_ETF_TAX_EXEMPT_END:
        return 0.0
    return ETF_TRANSACTION_TAX_RATE


def _validate_slippage(price: float, slippage_rate: float) -> tuple[float, float]:
    price, slippage_rate = float(price), float(slippage_rate)
    if price < 0:
        raise ValueError("price must be non-negative")
    if not 0 <= slippage_rate < 1:
        raise ValueError("slippage_rate must be in [0, 1)")
    return price, slippage_rate


def buy_fill_price(
    price: float, *, slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
) -> float:
    """Conservative buy fill used by every research and backtest path."""
    price, slippage_rate = _validate_slippage(price, slippage_rate)
    return price * (1 + slippage_rate)


def sell_fill_price(
    price: float, *, slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
) -> float:
    """Conservative sell fill used by every research and backtest path."""
    price, slippage_rate = _validate_slippage(price, slippage_rate)
    return price * (1 - slippage_rate)


def broker_commission(
    gross: float,
    *,
    fee_rate: float = BROKER_FEE_RATE,
    fee_discount: float = 1.0,
    minimum_fee: float = MINIMUM_BROKER_FEE,
) -> float:
    """Return broker commission for one side of a trade."""
    gross = float(gross)
    if fee_rate < 0 or fee_discount < 0 or minimum_fee < 0:
        raise ValueError("fee parameters must be non-negative")
    if gross < 0:
        raise ValueError("gross consideration must be non-negative")
    if gross == 0:
        return 0.0
    return max(gross * fee_rate * fee_discount, minimum_fee)


def buy_cash_outflow(
    shares: float,
    price: float,
    *,
    fee_rate: float = BROKER_FEE_RATE,
    fee_discount: float = 1.0,
    minimum_fee: float = MINIMUM_BROKER_FEE,
) -> float:
    """Cash paid for a buy: gross consideration plus broker commission."""
    shares, price = float(shares), float(price)
    if shares < 0 or price < 0:
        raise ValueError("shares and price must be non-negative")
    gross = shares * price
    return gross + broker_commission(
        gross,
        fee_rate=fee_rate,
        fee_discount=fee_discount,
        minimum_fee=minimum_fee,
    )


def sell_cash_inflow(
    shares: float,
    price: float,
    *,
    fee_rate: float = BROKER_FEE_RATE,
    fee_discount: float = 1.0,
    minimum_fee: float = MINIMUM_BROKER_FEE,
    tax_rate: float = STOCK_TRANSACTION_TAX_RATE,
) -> float:
    """Cash received for a sale after commission and seller-only transaction tax."""
    if tax_rate < 0:
        raise ValueError("tax_rate must be non-negative")
    shares, price = float(shares), float(price)
    if shares < 0 or price < 0:
        raise ValueError("shares and price must be non-negative")
    gross = shares * price
    return (
        gross
        - broker_commission(
            gross,
            fee_rate=fee_rate,
            fee_discount=fee_discount,
            minimum_fee=minimum_fee,
        )
        - gross * tax_rate
    )


def affordable_shares(
    cash: float,
    price: float,
    *,
    fee_rate: float = BROKER_FEE_RATE,
    fee_discount: float = 1.0,
    minimum_fee: float = MINIMUM_BROKER_FEE,
) -> float:
    """Maximum fractional shares whose buy cash outflow does not exceed ``cash``."""
    cash, price = float(cash), float(price)
    if fee_rate < 0 or fee_discount < 0 or minimum_fee < 0:
        raise ValueError("fee parameters must be non-negative")
    if cash <= 0 or price <= 0 or cash <= minimum_fee:
        return 0.0
    proportional = cash / (price * (1 + fee_rate * fee_discount))
    proportional_gross = proportional * price
    if proportional_gross * fee_rate * fee_discount >= minimum_fee:
        return proportional
    return (cash - minimum_fee) / price


def round_trip_return(
    entry_price: float,
    exit_price: float,
    *,
    entry_notional: float,
    fee_rate: float = BROKER_FEE_RATE,
    fee_discount: float = 1.0,
    minimum_fee: float = MINIMUM_BROKER_FEE,
    tax_rate: float = STOCK_TRANSACTION_TAX_RATE,
    slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
) -> float:
    """Net return including shared fills, commissions, and seller-only tax."""
    if entry_price <= 0 or exit_price < 0 or entry_notional <= 0:
        raise ValueError(
            "entry_price and entry_notional must be positive; exit_price cannot be negative")
    shares = float(entry_notional) / float(entry_price)
    paid = buy_cash_outflow(
        shares,
        buy_fill_price(entry_price, slippage_rate=slippage_rate),
        fee_rate=fee_rate,
        fee_discount=fee_discount,
        minimum_fee=minimum_fee,
    )
    received = sell_cash_inflow(
        shares,
        sell_fill_price(exit_price, slippage_rate=slippage_rate),
        fee_rate=fee_rate,
        fee_discount=fee_discount,
        minimum_fee=minimum_fee,
        tax_rate=tax_rate,
    )
    return received / paid - 1


def dividend_supplementary_premium(
    eligible_payment: float,
    *,
    enabled: bool = False,
    exempt: bool = False,
    rate: float = NHI_SUPPLEMENTARY_PREMIUM_RATE,
    threshold: float = NHI_DIVIDEND_PAYMENT_THRESHOLD,
    cap: float = NHI_DIVIDEND_PAYMENT_CAP,
) -> float:
    """Estimate NHI premium for one already-determined eligible dividend payment.

    ``enabled`` defaults to false because exact liability depends on the payment
    amount/date and the investor's insured/exempt status. It must never be called
    with sale proceeds or an ex-dividend price gap as a proxy.
    """
    payment = float(eligible_payment)
    if rate < 0 or threshold < 0 or cap < 0:
        raise ValueError("premium parameters must be non-negative")
    if not enabled or exempt or payment < threshold or payment <= 0:
        return 0.0
    return min(payment, cap) * rate


def per_share_cost_multipliers(
    *,
    is_etf: bool,
    fee_discount: float = 1.0,
    slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
    tax_rate: float | None = None,
) -> tuple[float, float]:
    """(買進乘數, 賣出乘數)：掛價 × 乘數 = 每股實際付出／收到的現金。

    與 `buy_cash_outflow` / `sell_cash_inflow` 同一套費率，但**不含最低手續費**——
    這是給「價位本身划不划算」的比例判斷用，與部位大小無關；部位小到撞最低 20 元時，
    實際成本只會更高。
    """
    if fee_discount < 0:
        raise ValueError("fee_discount must be non-negative")
    _validate_slippage(1.0, slippage_rate)
    fee = BROKER_FEE_RATE * fee_discount
    tax = tax_rate if tax_rate is not None else (ETF_TRANSACTION_TAX_RATE if is_etf else STOCK_TRANSACTION_TAX_RATE)
    if tax < 0:
        raise ValueError("tax_rate must be non-negative")
    return (1 + slippage_rate) * (1 + fee), (1 - slippage_rate) * (1 - fee - tax)
