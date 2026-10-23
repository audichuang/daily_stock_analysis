import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import tw_media_picks as mp  # noqa: E402

INDEX = [("3044.TW", "健鼎", []), ("6811.TWO", "宏碁資訊", []), ("0050.TW", "元大台灣50", ["台50"]),
         ("3374.TWO", "精材", []), ("2330.TW", "台積電", []),
         ("1111.TW", "某某電子", []), ("00981A.TW", "主動統一台股增長", []),
         ("00927.TW", "群益半導體收益", []), ("00929.TW", "復華台灣科技優息", []),
         ("00631L.TW", "元大台灣50正2", []), ("00850.TW", "元大臺灣ESG永續", []),
         ("6658.TW", "聯策", []), ("6438.TW", "迅得", []),
         ("6668.TW", "中揚光", []), ("00668.TW", "國泰美國道瓊", []), ("1303.TW", "南亞", []),
         ("0052.TW", "富邦科技", []), ("3029.TW", "零壹", [])]


def test_parse_answer_strips_fences_and_citations():
    text = '好的：\n```json\n[{"name": "健鼎", "stance": "bullish", "reason": "營收創高 [3, 5]"}, {"code": "x"}]\n```'
    picks = mp.parse_answer(text)
    assert picks == [{"name": "健鼎", "stance": "bullish", "reason": "營收創高"}]


def test_parse_answer_garbage_is_none_but_empty_list_is_no_picks():
    assert mp.parse_answer("沒有點名任何個股") is None
    assert mp.parse_answer("[not json]") is None
    assert mp.parse_answer("[]") == []
    # a bare citation marker is not "no picks": journaling it as no_picks would skip the episode forever
    assert mp.parse_answer("這集沒有列點名 [1]") is None
    assert mp.parse_answer("[1, 2]") is None
    # nameless objects are the model's way of saying "no picks": record them, don't retry until they age out
    assert mp.parse_answer('[{"name": null, "reason": "本集未點名個股"}]') == []
    assert mp.parse_answer("[{}]") == []


def test_resolve_order():
    assert mp.resolve("台積電公司", "2330", INDEX) == ("2330.TW", "code")
    # the name wins over a wrong code the LLM guessed
    assert mp.resolve("健鼎", "2330", INDEX) == ("3044.TW", "exact")
    assert mp.resolve("隨便", "2330", INDEX) == ("2330.TW", "code_mismatch")
    assert mp.resolve("臻鼎", None, [("4958.TW", "臻鼎-KY", [])]) == ("4958.TW", "exact")
    assert mp.resolve("健鼎", None, INDEX) == ("3044.TW", "exact")
    assert mp.resolve("台50", None, INDEX) == ("0050.TW", "alias")
    # misheard name with the correct one in parentheses
    assert mp.resolve("精綵（精材）", None, INDEX) == ("3374.TWO", "exact")
    assert mp.resolve("宏碁資訊（紅資訊/弘資訊）", None, INDEX) == ("6811.TWO", "exact")
    assert mp.resolve("台積", None, INDEX) == ("2330.TW", "fuzzy")
    assert mp.resolve("981A", "981A", INDEX) == ("00981A.TW", "code")
    # a number read out on air beats the ETF name the LLM filled in
    assert mp.resolve("復華台灣科技優息", "00927", INDEX, said="00927") == ("00927.TW", "code")
    assert mp.resolve("健鼎", None, INDEX, said="鑑頂") == ("3044.TW", "exact")
    assert mp.resolve("850", None, INDEX, said="850") == ("00850.TW", "code")
    assert mp.resolve("迅得", "6438", INDEX, said="6658 連測") == ("6658.TW", "code")
    assert mp.resolve("富邦科技", "0052", INDEX, said="52") == ("0052.TW", "code")
    # a misheard number that matches nothing falls back to the name / LLM code
    assert mp.resolve("元大台灣50", "0050", INDEX, said="5000") == ("0050.TW", "exact")
    assert mp.resolve("零壹", "3029", INDEX, said="01") == ("3029.TW", "exact")
    # fragments of spaced transcripts are not codes
    assert mp.resolve("中揚光", "6668", INDEX, said="668 中 陽 光") == ("6668.TW", "exact")
    assert mp.resolve("南亞", "1303", INDEX, said="130 連 南亞") == ("1303.TW", "exact")
    # a number that only matches after zero-padding loses to a name that resolves
    assert mp.resolve("中揚光", None, INDEX, said="668") == ("6668.TW", "exact")
    assert mp.resolve("國泰美國道瓊", None, INDEX, said="668") == ("00668.TW", "code")
    # the name is a homophone that resolves nothing, but the LLM's code contains the digits
    assert mp.resolve("中陽光", "6668", INDEX, said="668") == ("6668.TW", "code")
    assert mp.resolve("中揚光電", "6668", INDEX, said="668") == ("6668.TW", "code")
    # ...but only when the name's code contains the spoken digits; otherwise the number wins
    assert mp.resolve("國泰台灣領袖50", None, INDEX + [("00922.TW", "國泰台灣領袖50", [])], said="850") == ("00850.TW", "code")
    # digits inside a nickname are not a code
    assert mp.resolve("元大台灣50正2", None, INDEX, said="0050正2") == ("00631L.TW", "exact")


def test_resolve_does_not_force_a_match():
    # homophones share no characters; difflib can't recover them, so they must stay unresolved
    assert mp.resolve("建頂", None, INDEX) == (None, "unresolved")
    assert mp.resolve("某某科技", None, INDEX) == (None, "unresolved")
    assert mp.resolve("某某科技", "9999", INDEX) == (None, "unresolved")


def test_already_done_reads_video_ids(tmp_path):
    p = tmp_path / "j.jsonl"
    p.write_text("\n".join(json.dumps({"video_id": v}) for v in ("a", "b")) + "\n", encoding="utf-8")
    assert mp.already_done(p) == {"a", "b"}
    assert mp.already_done(tmp_path / "missing.jsonl") == set()


def test_new_episodes_filters_and_stops_at_first_old_video(monkeypatch):
    listing = "\n".join([
        "new1\t3000\t【節目】今天完整版",
        "clip\t300\t【節目】今天片段",          # too short
        "done\t3000\t【節目】已處理完整版",      # already in journal
        "old1\t3000\t【節目】前天完整版",
        "old2\t3000\t【節目】更早完整版",
    ])
    dates = {"new1": "20261021",  # exactly on --since: included
             "old1": "20261019", "old2": "20261018"}
    asked = []

    def fake_run(cmd, timeout=600):
        if "--flat-playlist" in cmd:
            return listing
        vid = cmd[-1].rsplit("=", 1)[1]
        asked.append(vid)
        return dates[vid]

    monkeypatch.setattr(mp, "_run", fake_run)
    monkeypatch.setattr(mp, "CHANNELS", [("節目", "tv", "UCx", r"完整版", 1200)])
    eps = mp.new_episodes(mp.date(2026, 10, 21), {"done"})
    assert [e["video_id"] for e in eps] == ["new1"]
    assert eps[0]["kind"] == "tv"
    # newest-first tab: stop at the first old video instead of fetching every date
    assert asked == ["new1", "old1"]


def test_nb_retries_timeouts_and_errors(monkeypatch):
    import subprocess
    from types import SimpleNamespace

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        if len(calls) == 2:
            return SimpleNamespace(returncode=1, stdout='{"error": true, "message": "rate limited"}', stderr="")
        return SimpleNamespace(returncode=0, stdout='{"answer": "[]"}', stderr="")

    monkeypatch.setattr(mp.subprocess, "run", fake_run)
    monkeypatch.setattr(mp.time, "sleep", lambda s: None)
    assert mp.nb("ask", "q") == {"answer": "[]"}
    assert len(calls) == 3


def test_nb_gives_up_after_attempts(monkeypatch):
    import subprocess

    def always_timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    monkeypatch.setattr(mp.subprocess, "run", always_timeout)
    monkeypatch.setattr(mp.time, "sleep", lambda s: None)
    try:
        mp.nb("ask", "q", attempts=2)
    except RuntimeError as exc:
        assert "timed out" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_snapshot_dependencies_exist():
    # snapshot() swallows errors per stock, so a moved helper would silently null every `data`
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()
    from src.services import tw_stock_dossier as dossier

    assert callable(dossier.fundamentals) and callable(dossier.chips)


def test_snapshot_skips_null_close_before_adjusting(monkeypatch):
    # 最後一天收盤是 NULL：不能把 NaN 寫進 journal，前復權也不能以那天為基準
    import math
    import pandas as pd
    from market_data import market_repo
    from src.services import tw_stock_dossier as dossier

    days = pd.bdate_range("2026-07-01", "2026-10-22")
    closes = [100.0] * (len(days) - 1) + [None]
    seen = {}
    monkeypatch.setattr(market_repo, "price_history",
                        lambda sid, start, end, engine: pd.DataFrame({"date": days, "close": closes}))

    def mult(sid, dates, engine):
        seen["last"] = pd.Timestamp(dates.iloc[-1])
        return pd.Series([1.0] * len(dates))

    monkeypatch.setattr(market_repo, "front_adjust_multipliers", mult)
    monkeypatch.setattr(dossier, "fundamentals", lambda *a, **k: {"monthly_revenue": []})
    monkeypatch.setattr(dossier, "chips", lambda *a, **k: {"institutional": None})
    out = mp.snapshot("2330.TW", days[-1].date(), engine=None)
    assert out["close"] == 100.0 and out["as_of"] == str(days[-2].date())
    assert seen["last"] == days[-2]
    assert not any(isinstance(v, float) and math.isnan(v) for v in out.values())
    json.dumps(out, allow_nan=False)


def test_single_run_lock_blocks_overlap():
    first = mp._single_run_lock()
    try:
        assert first is not None
        assert mp._single_run_lock() is None
    finally:
        first.close()
    again = mp._single_run_lock()
    assert again is not None
    again.close()


def test_air_date_comes_from_title_not_upload_date():
    # TVBS金臨天下 10-16 播的集數 10-20 才上傳：用上傳日當基準，data 會吃到播出後 4 個交易日的行情
    up = mp.date(2026, 10, 20)
    assert mp.air_date("【精彩鈔能力】台股慘跌 #財經鈔能力 20261016", up) == (mp.date(2026, 10, 16), "title")
    assert mp.air_date("投資明明很簡單 2026.10.19 #紀緯明", up) == (mp.date(2026, 10, 19), "title")
    assert mp.air_date("股市米琪林｜2026/10/20｜謝文琪", up) == (mp.date(2026, 10, 20), "title")
    # 標題沒日期、日期在上傳日之後、或早於上傳日兩週以上（講的是別的日子）都退回上傳日
    assert mp.air_date("台股打底量《股市情報局》", up) == (up, "upload")
    assert mp.air_date("明天 20261021 開獎", up) == (up, "upload")
    assert mp.air_date("回顧 20260101 那一波", up) == (up, "upload")
    assert mp.air_date("代號 2026 的股票 20261340", up) == (up, "upload")
    # 上傳日之前 14 天內都採用（含第 14 天）
    assert mp.air_date("x 20261006", up) == (mp.date(2026, 10, 6), "title")
    assert mp.air_date("x 20261005", up) == (up, "upload")


def test_premarket_shows_use_the_previous_close():
    aired = mp.date(2026, 10, 22)
    assert mp.data_cutoff("(字幕版) 2026.10.22 台股盤前 #財經早點名", aired) == mp.date(2026, 10, 21)
    evening = mp.datetime(2026, 10, 22, 21, 0, tzinfo=mp.TPE)
    assert mp.data_cutoff("(字幕版) 2026.10.22 台股盤前 #財經早點名", aired, evening) == mp.date(2026, 10, 21)
    assert mp.data_cutoff("(字幕版) 2026.10.22 台股盤後 #仁者無敵", aired, evening) == aired


def test_new_episodes_dates_by_air_date_but_filters_by_upload(monkeypatch):
    listing = "\n".join([
        "late\t3000\t【節目】完整版 20261016",   # 10-16 播、10-20 才上傳：在 --since 內
        "old\t3000\t【節目】完整版 20261020",    # 上傳日早於 --since：停
    ])
    dates = {"late": "20261020", "old": "20261018"}

    def fake_run(cmd, timeout=600):
        if "--flat-playlist" in cmd:
            return listing
        return dates[cmd[-1].rsplit("=", 1)[1]]

    monkeypatch.setattr(mp, "_run", fake_run)
    monkeypatch.setattr(mp, "CHANNELS", [("節目", "tv", "UCx", r"完整版", 1200)])
    eps = mp.new_episodes(mp.date(2026, 10, 19), set())
    assert [e["video_id"] for e in eps] == ["late"]
    ep = eps[0]
    assert ep["aired"] == mp.date(2026, 10, 16) and ep["aired_from"] == "title"
    assert ep["uploaded"] == mp.date(2026, 10, 20) and ep["cutoff"] == mp.date(2026, 10, 16)


def test_process_journals_air_date_and_snapshots_at_the_cutoff(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(mp, "nb", lambda *a, **k: {"answer": '[{"name": "台積電", "code": "2330"}]'})
    monkeypatch.setattr(mp, "TRANSCRIPTS", tmp_path)
    monkeypatch.setattr(mp, "snapshot", lambda code, as_of, engine: seen.append(as_of) or {"as_of": str(as_of)})
    ep = {"show": "節目", "kind": "tv", "video_id": "v", "url": "u", "title": "盤前 2026.10.22",
          "aired": mp.date(2026, 10, 22), "aired_from": "title", "uploaded": mp.date(2026, 10, 23),
          "cutoff": mp.date(2026, 10, 21), "source_id": "s"}
    rows = mp.process(ep, "nb", INDEX, engine=object())
    assert seen == [mp.date(2026, 10, 21)]
    assert rows[0]["date"] == "2026-10-22" and rows[0]["upload_date"] == "2026-10-23"
    assert rows[0]["date_source"] == "title"


def test_process_no_picks_row_carries_the_air_date_and_upload_date(monkeypatch, tmp_path):
    # 沒點名的集數也寫一行：date 是播出日（不是上傳日），也要有 upload_date／date_source，
    # 回驗才能用 date_source 分辨新舊口徑
    monkeypatch.setattr(mp, "nb", lambda *a, **k: {"answer": "[]"})
    monkeypatch.setattr(mp, "TRANSCRIPTS", tmp_path)
    ep = {"show": "節目", "kind": "tv", "video_id": "v", "url": "u", "title": "完整版 20261016",
          "aired": mp.date(2026, 10, 16), "aired_from": "title", "uploaded": mp.date(2026, 10, 20),
          "cutoff": mp.date(2026, 10, 16), "source_id": "s"}
    rows = mp.process(ep, "nb", INDEX, engine=None)
    assert len(rows) == 1 and rows[0]["resolve"] == "no_picks"
    assert rows[0]["date"] == "2026-10-16"
    assert rows[0]["upload_date"] == "2026-10-20" and rows[0]["date_source"] == "title"


def test_data_settled_waits_for_the_close_but_not_for_holidays(monkeypatch):
    monkeypatch.setattr(mp, "required_session", lambda d: {
        mp.date(2026, 10, 22): mp.date(2026, 10, 22),      # 平日
        mp.date(2026, 10, 24): mp.date(2026, 10, 23),      # 週六 -> 週五
    }[d])
    # 10-22 下午收盤還沒入庫：最新場次是 10-21，不能把前一天收盤寫成「播出當天」
    assert not mp.data_settled(mp.date(2026, 10, 22), mp.date(2026, 10, 21))
    assert mp.data_settled(mp.date(2026, 10, 22), mp.date(2026, 10, 22))
    # 休市那天之後已有新場次：那天本來就沒有收盤，用前一場是對的
    assert mp.data_settled(mp.date(2026, 10, 22), mp.date(2026, 10, 26))
    # 週六播出：要的是週五收盤，週五入庫就算定案
    assert mp.data_settled(mp.date(2026, 10, 24), mp.date(2026, 10, 23))
    assert not mp.data_settled(mp.date(2026, 10, 24), mp.date(2026, 10, 22))
    assert not mp.data_settled(mp.date(2026, 10, 22), None)


def test_required_session_skips_weekends_without_a_calendar(monkeypatch):
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()
    from src.core import trading_calendar

    monkeypatch.setattr(trading_calendar, "get_trading_dates", lambda *a, **k: None)
    assert mp.required_session(mp.date(2026, 10, 25)) == mp.date(2026, 10, 23)    # 週日 -> 週五
    assert mp.required_session(mp.date(2026, 10, 22)) == mp.date(2026, 10, 22)


def test_required_session_uses_the_exchange_calendar(monkeypatch):
    import pandas as pd
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()
    from src.core import trading_calendar

    # 平日休市（颱風假、國定假日）：10-22 週四休市，要的是 10-21 的收盤；只靠「跳過週末」會得到 10-22
    monkeypatch.setattr(trading_calendar, "get_trading_dates",
                        lambda m, s, e: pd.DatetimeIndex(["2026-10-20", "2026-10-21"]))
    assert mp.required_session(mp.date(2026, 10, 22)) == mp.date(2026, 10, 21)
    # 日曆回空（查不到）時退回平日判斷，不是報錯或回 None
    monkeypatch.setattr(trading_calendar, "get_trading_dates", lambda m, s, e: pd.DatetimeIndex([]))
    assert mp.required_session(mp.date(2026, 10, 22)) == mp.date(2026, 10, 22)
    assert mp.required_session(mp.date(2026, 10, 25)) == mp.date(2026, 10, 23)


def test_defer_unsettled_keeps_only_episodes_whose_close_is_in(monkeypatch):
    from market_data import market_repo

    # 10-22 行情整天被跳過（上櫃抓失敗），加權指數卻照樣寫進 10-22：閘門要看 market.price，不能看指數
    monkeypatch.setattr(market_repo, "latest_price_date", lambda engine=None: mp.date(2026, 10, 21))
    monkeypatch.setattr(market_repo, "latest_market_index",
                        lambda index_id, engine=None: {"date": mp.date(2026, 10, 22), "close": 1.0})
    monkeypatch.setattr(mp, "required_session", lambda d: d)
    eps = [{"video_id": v, "show": "s", "cutoff": d}
           for v, d in (("a", mp.date(2026, 10, 20)), ("b", mp.date(2026, 10, 21)), ("c", mp.date(2026, 10, 22)))]
    assert [e["video_id"] for e in mp.defer_unsettled(eps, engine=None)] == ["a", "b"]
    # 行情表查不到任何場次：全部延後（拿不到參照就拒收）
    monkeypatch.setattr(market_repo, "latest_price_date", lambda engine=None: None)
    assert mp.defer_unsettled(eps, engine=None) == []


def test_default_since_covers_episodes_deferred_over_a_weekend(monkeypatch):
    # 週五延後的集數（收盤沒入庫／颱風休市）要在週一那輪仍落在 --since 內，否則永遠漏掉
    seen = {}
    monkeypatch.setattr(mp, "_single_run_lock", lambda: object())
    monkeypatch.setattr(mp, "already_done", lambda: set())
    monkeypatch.setattr(mp, "new_episodes", lambda since, done: seen.setdefault("since", since) and [])
    assert mp.main(["--dry-run"]) == 0
    assert mp.date.today() - seen["since"] >= mp.timedelta(days=4)


def test_main_does_not_touch_notebooklm_when_every_episode_is_deferred(monkeypatch):
    from market_data import db

    ep = {"video_id": "v", "show": "s", "title": "t", "aired": mp.date(2026, 10, 22), "cutoff": mp.date(2026, 10, 22)}
    monkeypatch.setattr(mp, "_single_run_lock", lambda: object())
    monkeypatch.setattr(mp, "already_done", lambda: set())
    monkeypatch.setattr(mp, "new_episodes", lambda since, done: [ep])
    monkeypatch.setattr(mp, "load_index", lambda: INDEX)
    monkeypatch.setattr(db, "get_engine", lambda: object())
    deferred = []
    monkeypatch.setattr(mp, "defer_unsettled", lambda eps, engine: deferred.extend(eps) or [])

    def no_nb(*a, **k):
        raise AssertionError("deferred episodes must not reach NotebookLM or the journal")

    monkeypatch.setattr(mp, "nb", no_nb)
    assert mp.main(["--since", "2026-10-20"]) == 0
    assert deferred == [ep]


def test_latest_price_date_reads_market_price_and_handles_an_empty_table(monkeypatch):
    import pandas as pd

    from market_data import market_repo

    seen = []

    def fake_q(sql, params, engine):
        seen.append(sql)
        return pd.DataFrame({"d": [mp.date(2026, 10, 22)]})

    monkeypatch.setattr(market_repo, "_q", fake_q)
    assert market_repo.latest_price_date(engine=object()) == mp.date(2026, 10, 22)
    assert "market.price" in seen[0] and "market_index" not in seen[0]
    monkeypatch.setattr(market_repo, "_q", lambda sql, params, engine: pd.DataFrame({"d": [None]}))
    assert market_repo.latest_price_date(engine=object()) is None


def test_cutoff_uses_the_upload_time_when_the_title_does_not_say_盤前(monkeypatch):
    from datetime import datetime, timedelta, timezone

    tpe = timezone(timedelta(hours=8))

    def ts(h, m):
        return int(datetime(2026, 10, 6, h, m, tzinfo=tpe).timestamp())

    listing = "\n".join(["am\t1400\t20261006 盤中連線!分析師", "pm\t1400\t20261006 盤後分析師",
                         "early\t1400\t晨間節目"])
    # yt-dlp's upload_date is the UTC day: 07:00 Taipei is still 10-05 there
    meta = {"am": f"20261006 {ts(10, 3)}", "pm": f"20261006 {ts(19, 0)}", "early": f"20261005 {ts(7, 0)}"}

    def fake_run(cmd, timeout=600):
        if "--flat-playlist" in cmd:
            return listing
        return meta[cmd[-1].rsplit("=", 1)[1]]

    monkeypatch.setattr(mp, "_run", fake_run)
    monkeypatch.setattr(mp, "CHANNELS", [("節目", "tv", "UCx", r".", 1200)])
    meta["nots"] = "20261006 NA"  # no timestamp: assume the earliest moment of that UTC day
    listing += "\nnots\t1400\t20261006 晚間節目"
    eps = {e["video_id"]: e for e in mp.new_episodes(mp.date(2026, 10, 1), set())}
    assert eps["nots"]["cutoff"] == mp.date(2026, 10, 5)
    assert eps["am"]["cutoff"] == mp.date(2026, 10, 5)  # a morning segment only knows the previous close
    assert eps["pm"]["cutoff"] == mp.date(2026, 10, 6)
    assert eps["early"]["uploaded"] == mp.date(2026, 10, 6) and eps["early"]["cutoff"] == mp.date(2026, 10, 5)


def test_cutoff_without_an_upload_time_assumes_the_day_was_not_yet_public():
    # yt-dlp keeps upload_date but may drop the timestamp; a morning segment must not get that day's close
    assert mp.data_cutoff("20261006 盤中連線", mp.date(2026, 10, 6), None) == mp.date(2026, 10, 5)
