from datetime import date

from market_data import crawl


def test_daily_update_crawls_daily_sources_and_snapshots(monkeypatch):
    calls = []
    monkeypatch.setattr(crawl, "crawl_range",
                        lambda eng, src, dates, resume=True: calls.append(("range", src)))
    # `or 0`:真實 crawler 都回傳 upsert 列數,而 daily_update 會把它印出來
    # (`crawl_snapshots` 與月營收/除權息兩行),回 None 的 fake 會在格式化時炸掉
    monkeypatch.setattr(crawl, "crawl_valuation",
                        lambda conn: calls.append(("val",)) or 0)
    monkeypatch.setattr(crawl, "crawl_index",
                        lambda conn: calls.append(("idx",)) or 0)
    monkeypatch.setattr(crawl, "crawl_stock_info",
                        lambda conn: calls.append(("info",)) or 0)
    monkeypatch.setattr(crawl, "crawl_monthly_revenue",
                        lambda conn, month: calls.append(("rev", month)) or 0)
    monkeypatch.setattr(crawl, "crawl_ex_dividend",
                        lambda conn, start, end: calls.append(("exd", start, end)) or 0)

    class _Rows:
        def fetchall(self): return []          # 空庫 bootstrap:查不到歷史交易日

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a, **k): return _Rows()

    class _Eng:
        def begin(self): return _Conn()

    crawl.daily_update(engine=_Eng(), asof=date(2024, 6, 5), days=3)

    ranged = {c[1] for c in calls if c[0] == "range"}
    assert ranged == {"price", "institutional", "margin"}
    assert ("val",) in calls and ("idx",) in calls and ("info",) in calls
    # 上月營收(asof 6/5 -> 5 月)與除權息滾動窗(-30d ~ +90d)
    assert ("rev", date(2024, 5, 1)) in calls
    assert ("exd", date(2024, 5, 6), date(2024, 9, 3)) in calls
