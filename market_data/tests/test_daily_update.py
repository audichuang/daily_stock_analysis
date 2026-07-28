from datetime import date

from market_data import crawl


class _Result:
    """同時應付 `execute(...).fetchall()`(找歷史交易日)與 `.scalar()`(稽核 max(date))。"""

    def fetchall(self): return []              # 空庫 bootstrap:查不到歷史交易日
    def scalar(self): return date(2024, 6, 4)


class _Conn:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, *a, **k): return _Result()


class _Eng:
    def begin(self): return _Conn()
    def connect(self): return _Conn()          # `_snapshot_latest` 走獨立連線


def test_daily_update_crawls_daily_sources_and_snapshots(monkeypatch, capsys):
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
    # 只記錄再委派給真品:不這樣做的話,`daily_update` 退回「直接呼叫那三個函式」
    # 也會通過所有斷言,共用入口就白抽了(而共用入口正是「印出」不會再被漏掉的保證)
    real_snapshots = crawl.crawl_snapshots
    monkeypatch.setattr(crawl, "crawl_snapshots",
                        lambda eng: calls.append(("snapshots",)) or real_snapshots(eng))

    crawl.daily_update(engine=_Eng(), asof=date(2024, 6, 5), days=3)

    ranged = {c[1] for c in calls if c[0] == "range"}
    assert ranged == {"price", "institutional", "margin"}
    assert calls.count(("snapshots",)) == 1        # 走共用入口,不是三個直接呼叫
    assert ("val",) in calls and ("idx",) in calls and ("info",) in calls
    # 上月營收(asof 6/5 -> 5 月)與除權息滾動窗(-30d ~ +90d)
    assert ("rev", date(2024, 5, 1)) in calls
    assert ("exd", date(2024, 5, 6), date(2024, 9, 3)) in calls

    # 每一段都要留下可觀測的行——`daily` 全靜默正是這次要修的病
    out = capsys.readouterr().out
    for expect in ("valuation 0 rows", "index 0 rows", "stock_info 0 rows",
                   "monthly_revenue 2024-05 0 rows", "ex_dividend 0 rows"):
        assert expect in out, f"{expect!r} 沒印出來：{out!r}"
