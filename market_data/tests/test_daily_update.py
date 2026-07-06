from datetime import date

from market_data import crawl


def test_daily_update_crawls_daily_sources_and_snapshots(monkeypatch):
    calls = []
    monkeypatch.setattr(crawl, "crawl_range",
                        lambda eng, src, dates, resume=True: calls.append(("range", src)))
    monkeypatch.setattr(crawl, "crawl_valuation", lambda conn: calls.append(("val",)))
    monkeypatch.setattr(crawl, "crawl_index", lambda conn: calls.append(("idx",)))
    monkeypatch.setattr(crawl, "crawl_stock_info", lambda conn: calls.append(("info",)))

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Eng:
        def begin(self): return _Conn()

    crawl.daily_update(engine=_Eng(), asof=date(2024, 6, 5), days=3)

    ranged = {c[1] for c in calls if c[0] == "range"}
    assert ranged == {"price", "institutional", "margin"}
    assert ("val",) in calls and ("idx",) in calls and ("info",) in calls
