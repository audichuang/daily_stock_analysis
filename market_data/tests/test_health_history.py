"""health 的全歷史稽核：整日缺洞、上市-only 覆蓋率、非交易日復權事件數（免 DB，只報不擋）。

窗口內的缺日 `missing_*_dates` 只看最近 RECENT_SESSIONS 個交易日，一天整日沒列且滑出
窗口就永久無聲（institutional 2026-01-22／01-30、margin 01-30 實測如此）。
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from market_data import crawl, health

_D = date


def _days(*mds):
    return [_D(2026, m, d) for m, d in mds]


# --- full_history_gaps（純函式）---------------------------------------------

def test_a_whole_day_missing_in_the_middle_is_listed():
    price = _days((1, 21), (1, 22), (1, 23), (1, 26))
    table = _days((1, 21), (1, 23), (1, 26))

    assert health.full_history_gaps(price, table) == ["2026-01-22"]


def test_days_before_the_tables_first_date_are_not_gaps():
    """表是 2026-01-20 才開始收的；之前 price 有的日子是「還沒回補」，不算缺洞。"""
    price = _days((1, 15), (1, 16), (1, 20), (1, 21), (1, 22))
    table = _days((1, 20), (1, 22))

    assert health.full_history_gaps(price, table) == ["2026-01-21"]


def test_the_latest_price_session_is_excluded_as_t_plus_one():
    price = _days((1, 21), (1, 22), (1, 23))
    table = _days((1, 21))            # 22 與 23 都沒有；23 是最新日（T+1）不列

    assert health.full_history_gaps(price, table) == ["2026-01-22"]
    assert health.full_history_gaps(price, table, exclude_latest=False) == [
        "2026-01-22", "2026-01-23"]


def test_an_empty_table_or_empty_price_has_no_gaps():
    assert health.full_history_gaps(_days((1, 21)), []) == []
    assert health.full_history_gaps([], _days((1, 21))) == []


def test_string_and_datetime_dates_compare_equal():
    price = ["2026-01-21", "2026-01-22", "2026-01-23"]
    table = [datetime(2026, 1, 21), datetime(2026, 1, 23)]

    assert health.full_history_gaps(price, table) == ["2026-01-22"]


# --- report / run 接線 -------------------------------------------------------

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _RecordingConn:
    def __init__(self, plan, calls):
        self.plan, self.calls = plan, calls

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append((sql, params))
        for needle, rows in self.plan:
            if needle in sql:
                return _FakeResult(rows)
        return _FakeResult([])


# 日曆：01-21 ~ 01-30（略去週末），price 全有。
_PRICE = _days((1, 21), (1, 22), (1, 23), (1, 26), (1, 27), (1, 28), (1, 29), (1, 30))
_INST = [d for d in _PRICE if d != _D(2026, 1, 22) and d != _D(2026, 1, 30)]
_MARGIN = [d for d in _PRICE if d != _D(2026, 1, 30)]
_VALUATION = list(_PRICE[:-1])          # 只缺最新日 → T+1，不算缺洞
# 復權事件：01-24 是週六（非交易日）3 筆、01-23 在日曆上 2 筆、未來預告 02-10 不算
_ADJ = [(_D(2026, 1, 23), 2), (_D(2026, 1, 24), 3), (_D(2026, 2, 10), 9)]


def _engine(price=_PRICE, inst=_INST, margin=_MARGIN, valuation=_VALUATION,
            adj=_ADJ, first=()):
    calls = []
    plan = [
        *first,
        ("count(*), min(", [(1, price[0], price[-1])]),
        # 覆蓋率查詢也含 "FROM market.<t> WHERE"，必須排在近期視窗查詢之前
        ("count(DISTINCT stock_id) FROM market.price", [(2361,)]),
        ("count(DISTINCT stock_id) FROM market.institutional", [(1338,)]),
        ("count(DISTINCT stock_id) FROM market.margin", [(1100,)]),
        ("count(DISTINCT stock_id) FROM market.valuation", [(1330,)]),
        ("AND market IS NULL GROUP BY", []),
        ("AND market = :market GROUP BY", []),
        ("index_id = 'TAIEX' AND date >= :start",
         [(d,) for d in price[-crawl.RECENT_SESSIONS:]]),
        # 近期視窗（LIMIT :n）：假連線不處理參數，這裡直接給最後 RECENT_SESSIONS 天
        ("FROM market.price ORDER BY date DESC",
         [(d,) for d in reversed(price[-crawl.RECENT_SESSIONS:])]),
        # 全歷史查詢（無 WHERE / LIMIT）
        ("SELECT DISTINCT date FROM market.price ORDER BY date", [(d,) for d in price]),
        ("SELECT DISTINCT date FROM market.institutional WHERE true AND market IS NULL ORDER BY date",
         [(d,) for d in inst]),
        ("SELECT DISTINCT date FROM market.margin WHERE true AND market IS NULL ORDER BY date",
         [(d,) for d in margin]),
        ("SELECT DISTINCT date FROM market.valuation WHERE true AND market IS NULL ORDER BY date",
         [(d,) for d in valuation]),
        ("FROM market.institutional WHERE", [(d,) for d in inst]),
        ("FROM market.margin WHERE", [(d,) for d in margin]),
        ("FROM market.valuation WHERE", [(d,) for d in valuation]),
        ("FROM market.price_adjustment GROUP BY date", adj),
    ]

    class _Engine:
        def connect(self):
            return _RecordingConn(plan, calls)

    return _Engine(), calls


_NOW = datetime(2026, 1, 31, 18, 30, tzinfo=ZoneInfo("Asia/Taipei"))


def _is_session(day):
    """日曆回報『沒有應有場次』→ 跳過絕對新鮮度檢查，讓 strict 只剩視窗內缺日在決定結果。"""
    return False


def test_report_wires_history_gaps_coverage_and_offcalendar_events():
    engine, calls = _engine()

    result = health.report(engine, now=_NOW, is_session=_is_session)

    assert result["history_gaps"] == {
        "institutional": ["2026-01-22"],     # 01-30 是最新日 → T+1 不列
        "margin": [],
        "valuation": [],
    }
    assert result["coverage"]["institutional"] == {
        "date": "2026-01-29", "stocks": 1338, "price_stocks": 2361}
    assert result["coverage"]["margin"]["stocks"] == 1100
    assert result["offcalendar_adjustments"] == 3   # 只數 01-24；02-10 未來事件不算
    # 覆蓋率的比對日必須是「與 price 的最新共同日」，且查詢帶這一天
    count_days = {p["d"] for sql, p in calls if "count(DISTINCT stock_id)" in sql}
    assert count_days == {_D(2026, 1, 29)}


def test_report_lists_each_tables_own_gaps_independently():
    inst = [d for d in _PRICE if d not in (_D(2026, 1, 22), _D(2026, 1, 27))]
    margin = [d for d in _PRICE if d != _D(2026, 1, 28)]
    engine, _ = _engine(inst=inst, margin=margin)

    gaps = health.report(engine, now=_NOW, is_session=_is_session)["history_gaps"]

    assert gaps["institutional"] == ["2026-01-22", "2026-01-27"]
    assert gaps["margin"] == ["2026-01-28"]


def test_run_prints_the_three_lines_with_repair_commands(capsys):
    engine, _ = _engine()

    code = health.run(engine, strict=False, now=_NOW, is_session=_is_session)

    out = capsys.readouterr().out
    assert code == 0
    assert "full-history gaps institutional: 1 (latest 1) -> ['2026-01-22']" in out
    assert ("repair: uv run --env-file .env python -m market_data.cli "
            "backfill institutional --start 2026-01-22 --end 2026-01-22 --delay 3") in out
    assert "institutional 1338/2361 (2026-01-29)" in out
    assert "上市＋上櫃" in out
    assert "non-session dates: 3" in out
    assert "不要刪列" in out and "永久" in out


def test_run_lists_the_latest_ten_gaps_not_the_oldest(capsys):
    """老缺洞（2012）很多時，前 10 筆會把 2026-01-22 擠掉；要列最近的。"""
    old = [_D(2012, 1, 2) + timedelta(days=i) for i in range(30)]
    price = old + _PRICE
    inst_table = [old[0]] + [d for d in _PRICE if d != _D(2026, 1, 22)]
    engine, _ = _engine(price=price, inst=inst_table, margin=price, valuation=price)

    health.run(engine, strict=False, now=_NOW, is_session=_is_session)

    out = capsys.readouterr().out
    assert "full-history gaps institutional: 30 (latest 10)" in out
    assert "backfill institutional --start 2026-01-22 --end 2026-01-22" in out
    assert "--start 2012-01-03 " not in out


def test_history_gaps_alone_never_change_the_strict_result(capsys):
    """只報不擋：近期視窗（最後 5 個交易日）一切健康、只有窗口外有缺洞 → strict 回 0。"""
    # 缺洞在 01-22，不在最後 5 個交易日（01-23~01-30）之內
    engine, _ = _engine()

    assert health.run(engine, strict=True, now=_NOW, is_session=_is_session) == 0
    assert "full-history gaps institutional: 1" in capsys.readouterr().out


def test_strict_still_fails_on_a_real_recent_gap_with_history_lines_present(capsys):
    """反向：strict 照擋近期缺日，沒有被『只報不擋』誤關。"""
    inst = [d for d in _PRICE if d not in (_D(2026, 1, 28), _D(2026, 1, 30))]
    engine, _ = _engine(inst=inst)

    assert health.run(engine, strict=True, now=_NOW, is_session=_is_session) == 1


def test_run_tolerates_results_without_the_new_keys(monkeypatch):
    """舊形狀的 report()（測試 monkeypatch 的版本）沒有新欄位時 run 不能炸。"""
    monkeypatch.setattr(health, "report", lambda engine, **_: {
        "tables": {}, "thin_days": {}, "integrity": {}})

    assert health.run(engine=object(), strict=False) == 0


def test_tpex_gaps_are_reported_but_never_block_strict(capsys):
    """上櫃三表近期全缺（TPEx 掛了）：逐表列出，但 strict 仍回 0——上櫃單邊失敗不擋每日報告。"""
    engine, _ = _engine(first=[("AND market = :market", [])])

    assert health.run(engine, strict=True, now=_NOW, is_session=_is_session) == 0
    out = capsys.readouterr().out
    assert "missing institutional_tpex dates (只報不擋): 4" in out


def test_twse_recent_check_ignores_tpex_rows(capsys):
    """上市近期缺日只看上市列（market IS NULL）：同日只有上櫃列不能讓上市缺日過關。"""
    engine, _ = _engine(first=[("AND market IS NULL", [])])

    assert health.run(engine, strict=True, now=_NOW, is_session=_is_session) == 1
    assert "missing institutional dates: 4" in capsys.readouterr().out


def test_source_dates_isolates_markets_on_a_real_table(pg_conn):
    """假連線只比對 SQL 字串、驗不到過濾條件；這裡在真的表上種兩市場各一天。
    種子用 2099 年（本機 pg_conn 連正式庫，交易會 rollback）。"""
    from sqlalchemy import text as _text
    pg_conn.execute(_text("INSERT INTO market.institutional (stock_id, date) VALUES ('2330', '2099-05-01')"))
    pg_conn.execute(_text("INSERT INTO market.institutional (stock_id, date, market) "
                          "VALUES ('3324', '2099-05-02', 'tpex')"))
    start = _D(2099, 5, 1)
    assert health._source_dates(pg_conn, "institutional", None, start) == [_D(2099, 5, 1)]
    assert health._source_dates(pg_conn, "institutional", "tpex", start) == [_D(2099, 5, 2)]


def test_report_lists_tpex_thin_days_separately(capsys):
    # 上櫃融資／估值不在 REVISED_SOURCES：半套日寫進去就凍結，上市的 thin 稽核又只看 market IS NULL
    days = _days((1, 21), (1, 22), (1, 23), (1, 26), (1, 27), (1, 28))
    half = [(d, 400 if d == _D(2026, 1, 23) else 800) for d in days]
    engine, calls = _engine(first=[("FROM market.margin WHERE true AND market = :market GROUP BY", half)])
    result = health.report(engine, now=_NOW, is_session=_is_session)
    # 假連線不檢查參數：少傳 :market 時真的 Postgres 會直接拋例外、health --strict 整個崩
    tpex_calls = [p for sql, p in calls if "AND market = :market GROUP BY" in sql]
    assert len(tpex_calls) == 3 and all(p == {"market": "tpex"} for p in tpex_calls)
    assert result["thin_days_tpex"]["margin"] == [("2026-01-23", 400)]
    assert result["thin_days_tpex"]["institutional"] == []
    assert result["thin_days"]["margin"] == []          # 上市稽核不受影響
    health.run(engine, strict=False, now=_NOW, is_session=_is_session)
    assert "thin margin_tpex days (只報不擋): 1" in capsys.readouterr().out
