"""Crawl orchestration: fetch (finlab logic) -> etl transform -> upsert Postgres.

Replaces finlab's sqlite pipeline. Daily/date-based sources go through
``crawl_day``; ``crawl_range`` loops dates and skips ones already stored.
"""

import logging
import os
import shutil

import pandas as pd
from sqlalchemy import BigInteger, Integer, text

from market_data import crawler, etl, financial_statement, models, sources
from market_data.writer import dedupe, upsert

_VALID_ID = r"[0-9A-Za-z]{2,10}"


def _price_all(d, expected=None):
    """上市 (TWSE) + 上櫃 (TPEx) 合併。兩者都要有資料才回傳,否則回 None:
    若只有一邊成功就寫入,resume 會把該日標記完成、另一邊永久缺(TWSE/TPEx 同交易
    日),所以任一邊失敗就整天跳過,靠 date-not-in-table 下次重試。

    ``expected``(近幾日單日列數中位數)供截斷防護:TWSE 曾回「截斷但非空」的
    MI_INDEX(踩過:整天少 300+ 筆且數值錯位),非空檢查擋不住。合計低於九成
    先試 STOCK_DAY_ALL 備援換掉上市側,仍不足就整天跳過等下次重試。"""
    twse = crawler.crawl_price(d)
    otc = sources.crawl_tpex_price(d)
    if otc is None or not len(otc):
        return None

    def _low(t):
        n = (0 if t is None else len(t)) + len(otc)
        return expected is not None and n < 0.9 * expected

    if twse is None or not len(twse) or _low(twse):
        backup = sources.crawl_price_backup(d)
        if backup is not None and len(backup) > (0 if twse is None else len(twse)):
            print(f"**WARN price {d}: MI_INDEX missing/truncated, using STOCK_DAY_ALL backup")
            twse = backup
    if twse is None or not len(twse):
        return None
    if _low(twse):
        print(f"**WARN price {d}: {len(twse) + len(otc)} rows < 90% of recent "
              f"median {expected}, skipping day (will retry via resume)")
        return None
    return pd.concat([twse, otc])


def _recent_price_median(conn, around, k=5):
    """``around`` 附近 k 個交易日的單日列數中位數(截斷防護的期望值)。優先取
    之前的日期;沒有(空庫 bootstrap、daily_update 由新到舊迭代)就取之後的,
    否則倒序回補時除第一天外全程無防護。兩邊都沒有(全空庫第一天)回 None。"""
    for cmp_, order in (("<", "DESC"), (">", "ASC")):
        rows = conn.execute(text(
            f"SELECT COUNT(*) FROM market.price WHERE date {cmp_} :d "
            f"GROUP BY date ORDER BY date {order} LIMIT :k"),
            {"d": around, "k": k}).fetchall()
        if rows:
            counts = sorted(r[0] for r in rows)
            return counts[len(counts) // 2]
    return None


# date-based daily sources: name -> (fetch(date), transform, model, pk)
DAILY = {
    "price": (_price_all, etl.transform_price, models.Price, ["stock_id", "date"]),
    "institutional": (lambda d: sources.crawl_institutional(d),
                      etl.transform_institutional, models.Institutional,
                      ["stock_id", "date"]),
    "margin": (lambda d: sources.crawl_margin(d), etl.transform_margin,
               models.Margin, ["stock_id", "date"]),
    # valuation 走 BWIBBU_d(帶日期,可回補);daily 的快照仍走 BWIBBU_ALL。
    # fetch 已輸出 typed 英文欄位,故 transform 為 identity。
    "valuation": (lambda d: sources.crawl_valuation_day(d), lambda df: df,
                  models.Valuation, ["stock_id", "date"]),
}


def _to_records(df, table, filter_stock_id=True):
    df = df.copy()
    if filter_stock_id:
        sid = df["stock_id"]
        mask = sid.notna() & sid.astype(str).str.fullmatch(_VALID_ID)
        df = df[mask].copy()
    if df.empty:
        return []
    for c in table.columns:
        if isinstance(c.type, (Integer, BigInteger)) and c.name in df:
            df[c.name] = pd.to_numeric(df[c.name], errors="coerce").astype("Int64")
    df = df.astype(object).where(pd.notna(df), None)
    return df.to_dict("records")


def _records(df, table):
    return _to_records(df, table, filter_stock_id=True)


def _prepare(raw, transform, table, pk):
    """fetch 原始 frame -> 可寫入的 records(轉換+有效列過濾+PK 去重)。
    去重要在這層先做:replace 的 50% 門檻必須用 unique 後的筆數判斷。"""
    if raw is None or not len(raw):
        return []
    # finlab fetchers return frames indexed by (stock_id[, date]); the etl
    # transforms expect those as columns.
    if raw.index.names and raw.index.names[0] is not None:
        raw = raw.reset_index()
    return dedupe(_records(transform(raw), table), pk)


def _store(conn, raw, transform, model, pk, coalesce=()):
    recs = _prepare(raw, transform, model.__table__, pk)
    return upsert(conn, model.__table__, recs, pk, coalesce=coalesce)


def crawl_day(conn, source, d, replace=False):
    """抓一天並 upsert。``replace``:整日換血(同交易先刪該日既有列再寫)——修
    partial/髒日用;upsert 蓋不掉鍵已錯位的殘留列,必須刪。刪除的前置條件是
    「轉換+有效列過濾後真的有可寫資料,且不少於既有列數的一半」——來源回
    非空垃圾(全 footer/壞 stock_id)或嚴重縮水時絕不能先刪好資料。"""
    fetch, transform, model, pk = DAILY[source]
    if source == "price":
        raw = _price_all(d, expected=_recent_price_median(conn, d))
        coalesce = ("pe_ratio",)  # 備援缺本益比,重爬不得抹成 NULL
    else:
        raw = fetch(d)
        coalesce = ()
    recs = _prepare(raw, transform, model.__table__, pk)
    if replace and recs:
        existing = conn.execute(text(
            f"SELECT COUNT(*) FROM market.{model.__tablename__} "
            f"WHERE date = :d"), {"d": d}).scalar()
        if len(recs) < existing * 0.5:
            print(f"**WARN {source} {d}: replace refused — new {len(recs)} rows "
                  f"< 50% of existing {existing}, keeping current data")
            return 0
        conn.execute(text(
            f"DELETE FROM market.{model.__tablename__} WHERE date = :d"), {"d": d})
    return upsert(conn, model.__table__, recs, pk, coalesce=coalesce)


def crawl_monthly_revenue(conn, month_date):
    return _store(conn, crawler.crawl_monthly_report(month_date),
                  etl.transform_monthly_revenue, models.MonthlyRevenue,
                  ["stock_id", "revenue_month"])


def crawl_stock_info(conn):
    return _store(conn, sources.crawl_stock_info(), etl.transform_stock_info,
                  models.StockInfo, ["stock_id"])


def crawl_ex_dividend(conn, start, end):
    return _store(conn, sources.crawl_ex_dividend(start, end),
                  etl.transform_ex_dividend, models.ExDividend, ["stock_id", "date"])


def crawl_valuation(conn):
    rows = sources.fetch_valuation()
    if not rows:
        return 0
    df = etl.transform_valuation(rows).reset_index()
    recs = _to_records(df, models.Valuation.__table__, filter_stock_id=True)
    return upsert(conn, models.Valuation.__table__, recs, ["stock_id", "date"])


def crawl_index(conn):
    rows = sources.fetch_index()
    if not rows:
        return 0
    df = etl.transform_index(rows).reset_index()
    recs = _to_records(df, models.MarketIndex.__table__, filter_stock_id=False)
    return upsert(conn, models.MarketIndex.__table__, recs, ["index_id", "date"])


def crawl_snapshots(engine):
    """三個當日快照(valuation/index/stock_info),**每步一個交易**,逐個印出 upsert 列數。

    **唯一該呼叫快照的入口**——`daily_update` 與 `cli snapshot` 兩條路徑原本各自直接呼叫
    這三個函式且**把回傳值丟棄**,所以連成功都不印任何東西。少一個 `index 0 rows`,
    「TWSE 還沒發布」與「IP 被封 / 端點改版」就無法區分(踩過:2026-07-28 18:10 跑
    snapshot 全無輸出,得讀三層原始碼才知道是 FMTQIK 當日未發布)。輸出格式對齊
    `crawl_range` 的 `<source> <date> <n> rows`,方便同一份 cron log 一起 grep。

    **收 engine 而非 conn,而且一步一個交易**,理由有兩個,兩個都會讓 log 說謊:
    1. 三步共用一個交易時,前兩步印完「寫了 N 列」之後第三步一 raise,`engine.begin()`
       會把前兩步一起回滾——log 宣稱寫入、DB 其實沒有。印出的行必須代表**已 commit**。
    2. `_snapshot_latest` 的稽核查詢若在同一個交易裡失敗,Postgres 會把整個交易標成
       aborted;把例外吞掉並不會修復它,只會讓下一句 upsert 以「current transaction is
       aborted」失敗並回滾全部。所以稽核走**另一條連線、在 commit 之後**。

    三步互相獨立且 upsert 冪等,所以拆開沒有原子性損失:index 成功不該被 stock_info
    失敗抹掉。回傳 ``{name: rows}``,但**印出是這個函式的職責**——回傳值再被丟棄一次也
    不會退回全靜默。

    對應表刻意建在函式內:放在模組層會在 import 時就綁定函式物件,
    `monkeypatch.setattr(crawl, "crawl_index", …)` 就蓋不到(踩過,test_daily_update 紅)。
    """
    out = {}
    for name, fn in (("valuation", crawl_valuation),
                     ("index", crawl_index),
                     ("stock_info", crawl_stock_info)):
        with engine.begin() as conn:
            out[name] = n = fn(conn)
        print(f"{name} {n:,} rows{_snapshot_latest(engine, name)}")
    return out


# 有日期維度的快照表:列數本身**分不出**「當日資料有沒有進來」——這兩個端點都是回近月/
# 全市場的整包,TWSE 還沒發布當日資料時照樣回一樣多的列(實測 2026-07-28 18:10 拿到
# `index 18 rows`,而最新一列仍是 07-27)。所以要一併印最新日期,否則就是換一種靜默。
_SNAPSHOT_DATE_TABLES = {"valuation": "valuation", "index": "market_index"}


def _snapshot_latest(engine, name):
    """稽核用:該快照表目前的最新日期。**開自己的連線**——見 `crawl_snapshots` 理由 2,
    在寫入交易裡跑這句並吞掉例外會讓後續 upsert 全部回滾。"""
    table = _SNAPSHOT_DATE_TABLES.get(name)
    if table is None:                    # stock_info 無日期欄
        return ""
    try:
        with engine.connect() as c:
            d = c.execute(text(f"SELECT max(date) FROM market.{table}")).scalar()
    except Exception as exc:             # noqa: BLE001 — 稽核訊息不該讓爬取失敗
        return f", latest unknown ({type(exc).__name__})"
    return f", latest {d}"


_FINANCIAL_PK = ["stock_id", "date", "statement_type", "account"]


def _q4_income_sheet(conn, year, annual_cum):
    """Q4 單季損益 = 年報累計 − Q3 累計(讀 DB)。原 fill_season4 的增量版:
    年報 html 只有累計欄,單季值必須用同年度 Q3 累計(date=year-11-14)回推。"""
    q3 = pd.read_sql(
        text("SELECT stock_id, account, value FROM market.financial_statement "
             "WHERE statement_type='income_sheet_cumulate' AND date = :d"),
        conn, params={"d": f"{year}-11-14"})
    if q3.empty:
        print(f"**WARN: no Q3 {year} cumulate in DB, cannot derive Q4 income sheet")
        return None
    q3w = q3.pivot(index="stock_id", columns="account", values="value").astype(float)
    ann = annual_cum.reset_index().drop(columns=["date"]).set_index("stock_id")
    cols = [c for c in ann.columns if c in q3w.columns]  # 兩邊都是 累計X
    diff = ann[cols].apply(pd.to_numeric, errors="coerce").sub(
        q3w.reindex(ann.index)[cols])
    diff.columns = [c[2:] for c in cols]  # strip 累計 prefix
    diff["date"] = pd.to_datetime(f"{year + 1}-03-31")
    return diff.reset_index().set_index(["stock_id", "date"])


def crawl_financials(engine, year, season, keep_files=False, min_stocks=1000):
    """財報季更:下載該季 IFRS html 包(目錄已存在則沿用)→ 解析成寬表 →
    melt 長格式 upsert 進 market.financial_statement。冪等,可重跑。

    完整性 fail-fast(整季一個交易,失敗全回滾且保留下載檔供追查):
    解析出的股票數低於 ``min_stocks``(歷史最少一季 1748 檔)視為 partial
    quarter;Q4 需要同年 Q3 累計在庫才能推導單季損益,缺 Q3 直接失敗而不是
    默默寫入缺 income_sheet 的半套季資料。"""
    directory = os.path.join("data", "financial_statement", f"{year}{season}")
    partial_marker = os.path.join(directory, ".partial-quarter")
    # 目錄已存在則沿用——**除非**上次是被判為半季。截止日前抓到的那份不會自己長大，
    # 沿用它會讓截止日後的重跑再失敗一次，看起來像交易所沒發布。
    if os.path.isdir(directory) and os.path.exists(partial_marker):
        shutil.rmtree(directory, ignore_errors=True)
    if not os.path.isdir(directory):
        if year < 2019:
            raise NotImplementedError("僅支援 2019 年(含)以後的 IFRS 財報")
        crawler.crawl_finance_statement2019(year, season)
    frames = financial_statement.pack_htmls(year, season, directory)
    parsed = len(frames["balance_sheet"])
    if parsed < min_stocks:
        # 家數不足有**兩個**成因，從這裡分不出來：截止日前的半季發布，以及解析器
        # 對不上新版 markup。所以檔案要留著（後者需要它追查），但要標記成半季，
        # 讓下次重跑重新下載而不是沿用——不標的話，截止日後重跑會再失敗一次。
        try:
            with open(partial_marker, "w", encoding="utf-8") as fh:
                fh.write(f"parsed={parsed} min_stocks={min_stocks}\n")
        except OSError as exc:
            # 標記只是為了讓下次重跑重新下載，寫不進去不該蓋掉真正的錯誤——
            # 那會把「這季只有 525 檔」變成一個看不懂的 FileNotFoundError。
            logging.warning("could not mark %s as a partial quarter: %s", directory, exc)
        raise RuntimeError(
            f"{year}Q{season}: only {parsed} stocks parsed (<{min_stocks}), "
            f"quarter looks partial or the parser is out of date — nothing written; "
            f"files kept at {directory} for inspection and marked so a rerun re-downloads")
    table = models.FinancialStatement.__table__
    total = 0
    with engine.begin() as conn:
        if season == 4:
            q4 = _q4_income_sheet(conn, year, frames["income_sheet_cumulate"])
            if q4 is None:
                raise RuntimeError(
                    f"{year}Q4 needs Q3 cumulate in DB to derive the single-quarter "
                    f"income sheet — crawl season 3 first; nothing written")
            frames["income_sheet"] = q4
        for name, df in frames.items():
            if df is None or not len(df):
                continue
            long = etl.melt_financial(df.reset_index(), name)
            long = long.drop_duplicates(subset=_FINANCIAL_PK, keep="last")
            recs = _records(long, table)
            # 一季約 35 萬列,單條 INSERT 會超出參數上限,分批送
            for i in range(0, len(recs), 5000):
                total += upsert(conn, table, recs[i:i + 5000], _FINANCIAL_PK)
    if not keep_files:
        shutil.rmtree(directory, ignore_errors=True)
        if os.path.exists("temp.zip"):
            os.remove("temp.zip")
    return total


MAX_DAILY_RECOVERY_CALENDAR_DAYS = 31
# `daily` 自動修復的交易日視窗。**`health` 的近期完整性檢查必須用同一個數字**：檢查得比
# 修復得遠，就會出現「gate 擋住、但它叫你重跑的 daily 永遠補不到那一天」的死結。
RECENT_SESSIONS = 5


def recovery_dates(asof, recent, max_days=MAX_DAILY_RECOVERY_CALENDAR_DAYS):
    """Build the bounded automatic repair window; long gaps need explicit backfill."""
    import datetime as _dt

    start = min(recent) if recent else asof
    span = (asof - start).days
    if span > max_days:
        raise RuntimeError(
            f"daily recovery would scan {span + 1} calendar days ({start}..{asof}); "
            "run market_data.cli backfill explicitly for long gaps")
    return [start + _dt.timedelta(days=i)
            for i in range(span + 1)]


def daily_update(engine=None, asof=None, days=RECENT_SESSIONS):
    """Operational entry (replaces finlab's backfill): refresh the last ``days``
    trading days of daily sources + the daily snapshots. Resumable/idempotent."""
    import datetime as _dt

    from market_data import adjust
    from market_data.db import get_engine

    eng = engine or get_engine()
    asof = asof or _dt.date.today()
    # ``days`` 是**交易日**不是曆日:用 5 個曆日的話,週末＋連假一來實際只回補 2~3 個交易日,
    # 而法人/融資是 T+1 才補齊的,窗口太窄會讓那幾天永久缺。asof 自己也要進去——當日的
    # price 還沒入庫,不會出現在下面查到的歷史交易日裡。
    with eng.begin() as conn:
        recent = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT date FROM market.price WHERE date <= :d "
            "ORDER BY date DESC LIMIT :n"), {"d": asof, "n": days}).fetchall()]
    dates = recovery_dates(asof, recent)
    for source in ("price", "institutional", "margin"):
        crawl_range(eng, source, dates)
    crawl_snapshots(eng)
    # 月營收(上月整月)與除權息(滾動窗)順帶保鮮:各一個請求,upsert 冪等
    prev_month = (asof.replace(day=1) - _dt.timedelta(days=1)).replace(day=1)
    with eng.begin() as conn:
        rev = crawl_monthly_revenue(conn, prev_month)
        exd = crawl_ex_dividend(conn, asof - _dt.timedelta(days=30),
                                asof + _dt.timedelta(days=adjust.ADJUSTMENT_WINDOW_DAYS))
    # commit 之後才印——在交易內印,後面一 raise 就會回滾,log 卻已宣稱寫入
    print(f"monthly_revenue {prev_month:%Y-%m} {rev:,} rows")
    print(f"ex_dividend {exd:,} rows")
    try:
        adjust.refresh_recent(
            eng, asof - _dt.timedelta(days=adjust.ADJUSTMENT_WINDOW_DAYS),
            asof + _dt.timedelta(days=adjust.ADJUSTMENT_WINDOW_DAYS))
    except Exception as exc:
        raise RuntimeError(
            "daily source updates completed, but price_adjustment refresh failed; "
            "fix the reported official source and rerun daily before screening") from exc


def pit_revenue_gaps(conn, start, end, only=None):
    """回傳 [(stock_id, year, month)]:當月有交易、但 `monthly_revenue` 缺該月的組合。

    只針對**已停止交易**的股票。這是修存活偏誤:月營收彙總報表 `t21sc03` 是動態產生的,
    只列目前仍在申報的公司,所以後來下市的公司在歷史回補裡永久缺席——而選股要求
    `yoy >= 20`,等於整個負尾被系統性移除。

    **下市判定用 `price` 表最後交易日,不是「不在 `stock_info` 裡」**——`stock_info` 只含
    上市(TWSE)約 1,100 檔,用它判定會把全部上櫃公司都當成下市(實測會從 70 檔暴增到 973 檔)。
    上櫃公司的月營收缺漏是另一件事(彙總報表只走 `/sii/`),那是覆蓋範圍限制而非存活偏誤。
    """
    rows = conn.execute(text("""
        with last_day as (select max(date) d from market.price),
        traded as (
          select p.stock_id,
                 extract(year from p.date)::int  y,
                 extract(month from p.date)::int m
          from market.price p
          where p.date between :s and :e
            and length(p.stock_id) = 4 and p.stock_id ~ '^[0-9]{4}$'
            and p.stock_id not like '00%' and p.stock_id not like '91%'
            and p.stock_id in (
              select stock_id from market.price
              group by stock_id
              having max(date) < (select d from last_day) - interval '14 days')
          group by 1, 2, 3
        )
        select t.stock_id, t.y, t.m from traded t
        where not exists (
          select 1 from market.monthly_revenue r
          where r.stock_id = t.stock_id
            and extract(year from r.revenue_month)::int = t.y
            and extract(month from r.revenue_month)::int = t.m)
        order by t.stock_id, t.y, t.m
    """), {"s": start, "e": end}).fetchall()
    gaps = [(r[0], r[1], r[2]) for r in rows]
    if only is not None:
        want = set(only)
        gaps = [g for g in gaps if g in want]
    return gaps


# 只有這兩個原因代表「這家公司真的補不回來」，可以跳過其餘月份。其他失敗（HTTP、解析、
# 月份不符、單月無資料）都是暫時或個別月份的問題，不能據此放棄整檔——否則「補不回的
# 公司數」會被 HTTP 失敗虛胖，而那個數字正是存活偏誤殘餘量的分母。
_TERMINAL_REASONS = ("not_public", "foreign_exempt")


def backfill_pit_revenue(engine, start, end, delay=3.0, limit=None, only=None):
    """逐公司逐月補下市公司的月營收（MOPS 個別公司查詢）。回傳統計 dict。

    `delay` 是每次請求後的間隔——MOPS 同屬 TWSE,密集請求會被擋。
    失敗原因分開統計（見 `_TERMINAL_REASONS`）:只有「不繼續公開發行／外國發行人免申報」
    才是硬邊界並跳過該公司其餘月份;HTTP 或解析失敗會留在 `retryable`,下次執行時
    `pit_revenue_gaps` 仍會列出來重試。
    """
    import time as _time
    from collections import Counter

    with engine.begin() as conn:
        gaps = pit_revenue_gaps(conn, start, end, only=only)
    if limit:
        gaps = gaps[:limit]
    stats = {"requested": 0, "written": 0, "reasons": Counter(),
             "stocks_ok": set(), "stocks_terminal": {}, "retryable": []}
    for sid, y, m in gaps:
        if sid in stats["stocks_terminal"]:
            continue          # 整檔不繼續公開發行,不用逐月重試
        rec, reason = sources.crawl_company_monthly_revenue(sid, y, m)
        stats["requested"] += 1
        stats["reasons"][reason] += 1
        if rec is None:
            if reason in _TERMINAL_REASONS:
                stats["stocks_terminal"][sid] = reason
            else:
                stats["retryable"].append((sid, y, m, reason))
            print(f"revenue-pit {sid} {y}-{m:02d} {reason}", flush=True)
        else:
            with engine.begin() as conn:
                stats["written"] += upsert(
                    conn, models.MonthlyRevenue.__table__, [rec],
                    ["stock_id", "revenue_month"])
            stats["stocks_ok"].add(sid)
            print(f"revenue-pit {sid} {y}-{m:02d} yoy={rec['yoy']}", flush=True)
        if delay:
            _time.sleep(delay)
    stats["stocks_ok"] = sorted(stats["stocks_ok"])
    return stats


def _existing_dates(conn, table):
    rows = conn.execute(text(f"SELECT DISTINCT date FROM market.{table}")).fetchall()
    return {r[0].isoformat() for r in rows}


_MAX_EMPTY_STREAK = 4
# price 自己就是交易日曆的來源,沒有日曆可過濾假日,只能退回「擋週末」。此時零列的正常
# 解釋還在(國定假日),門檻必須高過最長的連續平日休市——2024 春節休市 2/6~2/14 是連續
# 7 個平日,取 10 留餘裕。踩過:用 4 去回補跨春節的 price 會被誤判成 IP 封鎖而中止。
_MAX_EMPTY_STREAK_NO_CALENDAR = 10


def _trading_dates(conn, start, end):
    """``market.price`` 已存的交易日(唯一在庫的真實台股行事曆)。用它過濾回補區間,
    才不會把請求額度花在假日上——猜不到的假日很多:2024 春節休市 2/6~2/14 就是連續
    7 個平日,單靠 weekday 擋不掉。price 自己不能用這條(空庫 bootstrap 沒基準)。"""
    rows = conn.execute(text(
        "SELECT DISTINCT date FROM market.price WHERE date BETWEEN :s AND :e"),
        {"s": start, "e": end}).fetchall()
    return {r[0] for r in rows}


def crawl_range(engine, source, dates, resume=True, replace=False, delay=0.0):
    """Crawl a list of dates for a daily source, upserting each; skips dates
    already present when resume=True (any row counts as done — partial days
    need ``resume=False, replace=True`` to be repaired). Returns rows written.

    ``delay``:每次抓取後的間隔秒數。長區間回補務必給值——TWSE 會在密集請求後暫時
    封鎖 IP,而失敗是**靜默**的(`requests_get` 回 None → 該日跳過、不報錯),
    踩過:回補 1,600 天的 valuation 只寫進 40 天就被擋,輸出還是空的。

    兩道省請求/止血機制:非交易日不發請求(見 ``_trading_dates``);連續 N 個**已知交易日**
    回零列就 raise——過濾掉假日之後零列不再有正常解釋,不該安靜跳完剩下幾百天。門檻依
    有沒有日曆而不同(見 ``_MAX_EMPTY_STREAK_NO_CALENDAR``)。
    """
    import time as _time

    table = DAILY[source][2].__tablename__
    total = 0
    with engine.begin() as conn:
        have = _existing_dates(conn, table) if resume else set()
        cal = (_trading_dates(conn, min(dates), max(dates))
               if source != "price" and dates else set())
    limit = _MAX_EMPTY_STREAK if cal else _MAX_EMPTY_STREAK_NO_CALENDAR
    unit = "trading days" if cal else "weekdays"
    empty_streak = 0
    for d in dates:
        if d.weekday() >= 5 or (cal and d not in cal):
            continue
        if resume and d.isoformat() in have:
            continue
        with engine.begin() as conn:
            n = crawl_day(conn, source, d, replace=replace)
        total += n
        print(f"{source} {d} {n:,} rows", flush=True)
        empty_streak = 0 if n else empty_streak + 1
        if empty_streak >= limit:
            raise RuntimeError(
                f"{source}: {empty_streak} consecutive {unit} returned 0 rows "
                f"(last {d}) — likely IP-blocked or the endpoint changed. "
                f"Stopping instead of silently skipping the rest; resume will "
                f"pick up where this left off.")
        if delay:
            _time.sleep(delay)
    return total
