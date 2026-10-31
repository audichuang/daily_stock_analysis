"""行事曆來源、隔離快取、API 與分析證據的定向測試。"""
import threading
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient as Client
from sqlalchemy import inspect, select

from api.v1.endpoints.calendar import router, get_calendar_service
from src.config import Config
from src.repositories.calendar_repo import CalendarRepository
from src.services import calendar_sources as sources
from src.services import calendar_service as service
from src.storage import DatabaseManager, DatabaseSchemaMigration


@pytest.fixture
def clock():
    return datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('STOCK_LIST=AAPL,2330.TW\nSTOCK_INDEX_REMOTE_UPDATE_ENABLED=false\n')
    monkeypatch.setenv('ENV_FILE', str(env))
    monkeypatch.setenv('STORAGE_DATABASE_URL', '')
    monkeypatch.setenv('DATABASE_URL', '')
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'calendar.db'))
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    yield CalendarRepository(db)
    DatabaseManager.reset_instance()
    Config.reset_instance()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('unexpected outbound request')
    monkeypatch.setattr(sources, 'nasdaq_json', blocked)
    monkeypatch.setattr(sources, 'yahoo_earnings', blocked)
    monkeypatch.setattr(service, 'fetch_tw_conferences', blocked)
    monkeypatch.setattr(service, 'CONFERENCE_REQUEST_GAP_SECONDS', 0)


def row(clock, code='AAPL', days=3, **fields):
    return {'id': f'earnings:{code}', 'type': 'earnings', 'code': code, 'name': code,
            'date': (clock + timedelta(days=days)).date(), 'status': 'confirmed', 'detail': '盤後',
            'source_url': 'https://www.nasdaq.com/', 'timezone': 'America/New_York', 'date_kind': 'release',
            'updated_at': clock.replace(tzinfo=None), **fields}


def announcement(day):
    return {'announcement': day.strftime('%b %d, %Y'),
            'reportText': 'derived from an algorithm; consensus EPS forecast for the quarter is $-0.25'}


def calendar(day, symbol='AAPL'):
    return {'asOf': day.strftime('%a, %b %d, %Y'), 'rows': [
        {'symbol': symbol, 'time': 'time-after-hours', 'epsForecast': '$1.5'}]}


def test_nasdaq_no_date_and_estimate(clock):
    assert sources.parse_earnings_date('GOOGL', {'announcement': '', 'reportText': "hasn't provided"}) is None
    got = sources.parse_earnings_date('AAPL', announcement(clock.date()))
    assert got['date'] == clock.date() and got['status'] == 'estimated'
    assert '$-0.25' in got['detail']


def test_calendar_only_confirms_matching_day_and_class_symbol(clock):
    day = clock.date()
    got = sources.parse_earnings_calendar('BRK-B', day, calendar(day, 'BRK.B'))
    assert got['status'] == 'estimated' and '盤後' in got['detail'] and '$1.5' in got['detail']
    assert sources.parse_earnings_calendar('AAPL', day, calendar(day, 'GOOGL')) is None
    with pytest.raises(ValueError, match='日期不符'):
        sources.parse_earnings_calendar('AAPL', day, calendar(day - timedelta(days=79)))
    with pytest.raises(ValueError):
        sources.parse_earnings_calendar('AAPL', day, {'rows': calendar(day)['rows']})


def test_fetch_nasdaq_primary_and_calendar_failure_is_estimate(clock, monkeypatch):
    day = clock.date() + timedelta(days=2)
    calls = []

    def fetch(path):
        calls.append(path)
        return announcement(day) if 'earnings-date' in path else calendar(day, 'BRK.B')
    monkeypatch.setattr(sources, 'nasdaq_json', fetch)
    got = sources.fetch_earnings('BRK.B', clock.date())
    assert got['status'] == 'estimated' and 'analyst/BRK.B/' in calls[0]
    monkeypatch.setattr(sources, 'nasdaq_json', Mock(side_effect=[announcement(day), ValueError('frozen')]))
    assert sources.fetch_earnings('AAPL', clock.date())['status'] == 'estimated'


def test_no_date_fallback_and_both_failures(clock, monkeypatch):
    day = clock.date()
    monkeypatch.setattr(sources, 'nasdaq_json', lambda p: {})
    yahoo = Mock(return_value=None)
    monkeypatch.setattr(sources, 'yahoo_earnings', yahoo)
    assert sources.fetch_earnings('GOOGL', day) is None
    yahoo.assert_called_once()
    yahoo.return_value = {'date': day, 'status': 'estimated'}
    assert sources.fetch_earnings('GOOGL', day)['status'] == 'estimated'
    monkeypatch.setattr(sources, 'nasdaq_json', Mock(side_effect=RuntimeError('Nasdaq down')))
    yahoo.side_effect = RuntimeError('Yahoo throttled')
    with pytest.raises(RuntimeError):
        sources.fetch_earnings('AAPL', day)
    monkeypatch.setattr(sources, 'nasdaq_json', lambda p: {})
    assert sources.fetch_earnings('GOOGL', day) is None


def test_past_nasdaq_date_not_used(clock, monkeypatch):
    monkeypatch.setattr(sources, 'nasdaq_json', lambda p: announcement(clock.date() - timedelta(days=1)))
    monkeypatch.setattr(sources, 'yahoo_earnings', lambda c, d: None)
    assert sources.fetch_earnings('AAPL', clock.date()) is None


def test_only_yahoo_flag_confirms_and_its_failure_keeps_estimate(clock, monkeypatch):
    day = clock.date() + timedelta(days=4)
    monkeypatch.setattr(sources, 'nasdaq_json', Mock(side_effect=lambda p: (
        announcement(day) if 'analyst' in p else calendar(day))))
    moved = day + timedelta(days=1)
    monkeypatch.setattr(sources, 'yahoo_earnings', lambda c, d: {'date': moved, 'status': 'estimated'})
    got = sources.fetch_earnings('AAPL', clock.date())
    assert got['status'] == 'estimated' and got['date'] == day
    monkeypatch.setattr(sources, 'yahoo_earnings', lambda c, d: {'date': moved, 'status': 'confirmed'})
    got = sources.fetch_earnings('AAPL', clock.date())
    assert got['status'] == 'confirmed' and got['date'] == moved
    monkeypatch.setattr(sources, 'yahoo_earnings', Mock(side_effect=ValueError('empty')))
    got = sources.fetch_earnings('AAPL', clock.date())
    assert got['status'] == 'estimated' and got['date'] == day


def test_yahoo_estimate_flag_sets_status(clock, monkeypatch):
    import yfinance
    stamp = int((clock + timedelta(days=4)).timestamp())
    for flag, status in ((False, 'confirmed'), (True, 'estimated'), (None, 'estimated')):
        monkeypatch.setattr(yfinance, 'Ticker', lambda code, f=flag: SimpleNamespace(
            info={'symbol': 'AAPL', 'earningsTimestamp': stamp, 'isEarningsDateEstimate': f}, calendar={}))
        assert _raw_yahoo()('AAPL', clock.date())['status'] == status


def test_macro_refresh_keeps_later_cached_dates(repo, clock):
    def macro(days):
        day = (clock + timedelta(days=days)).date()
        return {**row(clock, days=days), 'id': f'pce:{day}', 'type': 'pce', 'code': None, 'date': day}
    repo.replace_macro_type('pce', [macro(-5), macro(90)])
    repo.replace_macro_type('pce', [macro(-5), macro(10)])
    days = sorted(r['date'] for r in repo.read([], clock.date() - timedelta(days=9), date.max) if r['type'] == 'pce')
    assert days == [(clock + timedelta(days=d)).date() for d in (-5, 10, 90)]


def _raw_yahoo():
    # 呼叫原始 Yahoo 解析接縫，不使用 autouse 替換的函式。
    import importlib.util
    spec = importlib.util.spec_from_file_location('calendar_yahoo_test', sources.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.yahoo_earnings


@pytest.mark.parametrize("eps,expected", [(1.5, "$1.5"), (0.0, "$0"), (None, None), (float("nan"), None)])
def test_yahoo_date_range_and_eps(clock, monkeypatch, eps, expected):
    import yfinance
    future = clock + timedelta(days=4)
    monkeypatch.setattr(yfinance, 'Ticker', lambda code: SimpleNamespace(
        info={'symbol': 'BRK-B', 'earningsTimestampStart': int((clock - timedelta(days=2)).timestamp()),
              'earningsTimestamp': int(future.timestamp()),
              'earningsTimestampEnd': int((future + timedelta(days=2)).timestamp())},
        calendar={'Earnings Average': eps}))
    got = _raw_yahoo()('BRK.B', clock.date())
    assert got['date'] == future.date() and got['status'] == 'estimated' and 'BRK-B' in got['source_url']
    assert (expected in got['detail']) if expected else ('EPS' not in got['detail'])


@pytest.mark.parametrize("stamp,expected", [
    (datetime(2036, 11, 5, 21, 30, tzinfo=timezone.utc), date(2036, 11, 5)),
    # 跨月：美東 10/31 盤後，台北已是 11/1。
    (datetime(2036, 11, 1, 0, 30, tzinfo=timezone.utc), date(2036, 10, 31)),
])
def test_yahoo_after_hours_keeps_eastern_date_on_taipei_host(monkeypatch, stamp, expected):
    import time
    import yfinance
    monkeypatch.setenv('TZ', 'Asia/Taipei')
    time.tzset()
    try:
        monkeypatch.setattr(yfinance, 'Ticker', lambda code: SimpleNamespace(
            info={'symbol': 'AAPL', 'earningsTimestamp': int(stamp.timestamp())}, calendar={}))
        assert _raw_yahoo()('AAPL', date(2036, 1, 1))['date'] == expected
    finally:
        monkeypatch.delenv('TZ')
        time.tzset()


def test_yahoo_empty_response_is_failure_but_no_date_is_none(clock, monkeypatch):
    import yfinance
    monkeypatch.setattr(yfinance, 'Ticker', lambda code: SimpleNamespace(info={}, calendar={}))
    with pytest.raises(ValueError):
        _raw_yahoo()('AAPL', clock.date())
    monkeypatch.setattr(yfinance, 'Ticker', lambda code: SimpleNamespace(info={'symbol': 'AAPL'}, calendar={}))
    assert _raw_yahoo()('AAPL', clock.date()) is None


def test_both_sources_down_keeps_cached_date(repo, clock, monkeypatch):
    repo.save_earnings(row(clock))
    monkeypatch.setattr(sources, 'nasdaq_json', Mock(side_effect=RuntimeError('503')))
    monkeypatch.setattr(sources, 'yahoo_earnings', Mock(side_effect=ValueError('empty')))
    svc = service.CalendarService(repo, members_provider=lambda: {'AAPL': 'Apple'})
    monkeypatch.setattr(svc, '_refresh_macro', lambda now: None)
    assert svc.refresh(now=clock)['failed'] == 1
    assert repo.read(['AAPL'], clock.date(), date.max)[0]['date'] == (clock + timedelta(days=3)).date()


MOPS_ROW = ('<tr><td>{code}</td><td>{name}</td><td>{day}</td><td>14:00</td><td>線上</td>'
            '<td>說明營運&amp;展望</td><td>檔</td></tr>')
MOPS_HEAD = '<table><tr><th>公司代號</th></tr>'


def test_mops_parse_rows_month_guard_and_error_pages():
    body = MOPS_HEAD + MOPS_ROW.format(code='2330', name='台積電', day='115/11/02') + (
        MOPS_ROW.format(code='00631L', name='跨月', day='115/10/30 至 115/11/03')) + '</table>'
    rows = sources.parse_mops_conferences(body, 2026, 11)
    assert [(r['code'], r['date']) for r in rows] == [('2330', date(2026, 11, 2)), ('00631L', date(2026, 10, 30))]
    assert rows[0]['summary'] == '說明營運&展望'
    assert sources.parse_mops_conferences('<div>查無資料</div>', 2026, 11) == []
    with pytest.raises(ValueError, match='月份'):
        sources.parse_mops_conferences(body, 2026, 12)
    with pytest.raises(ValueError, match='彙總表'):
        sources.parse_mops_conferences('<html>FOR SECURITY REASONS</html>', 2026, 11)


def conference_service(repo, clock, monkeypatch, fetch):
    monkeypatch.setattr(service, 'fetch_tw_conferences', fetch)
    monkeypatch.setattr(service, 'CONFERENCE_REQUEST_GAP_SECONDS', 0)
    monkeypatch.setattr(service, 'fetch_earnings', lambda c, d: None)
    svc = service.CalendarService(repo, members_provider=lambda: {'2330.TW': '台積電', '6488.TWO': '環球晶'})
    monkeypatch.setattr(svc, '_refresh_macro', lambda now: None)
    return svc


def test_refresh_keeps_member_future_conferences_only(repo, clock, monkeypatch):
    day = (clock + timedelta(days=5)).date()
    item = dict(date=day, date_text='x', time='14:00', place='線上', summary='法說')

    def fetch(year, month, market):
        if market == 'sii' and (year, month) == (clock.year, clock.month):
            return [{**item, 'code': '2330', 'name': '台積電'},
                    {**item, 'code': '1101', 'name': '非名單', 'date': day + timedelta(days=1)},
                    {**item, 'code': '2330', 'name': '台積電', 'date': clock.date() - timedelta(days=2)}]
        if market == 'otc' and (year, month) == (clock.year, clock.month):
            return [{**item, 'code': '6488', 'name': '環球晶'}]
        return []

    svc = conference_service(repo, clock, monkeypatch, fetch)
    assert svc.refresh(now=clock)['conferences'] == 2
    rows = [r for r in repo.read(['2330.TW', '6488.TWO'], clock.date() - timedelta(days=9), date.max)
            if r['type'] == service.CONFERENCE_TYPE]
    assert sorted(r['code'] for r in rows) == ['2330.TW', '6488.TWO']
    assert rows[0]['name'].endswith('法說會') and rows[0]['timezone'] == 'Asia/Taipei'
    # 法說會只是證據事件，個股仍可取得，但型別不冒充財報。
    assert svc.next_earnings('2330.TW', now=clock)['type'] == service.CONFERENCE_TYPE


def test_conference_failure_keeps_previous_cache(repo, clock, monkeypatch):
    day = (clock + timedelta(days=5)).date()
    good = [{'code': '2330', 'name': '台積電', 'date': day, 'date_text': 'x', 'time': '', 'place': '', 'summary': ''}]
    svc = conference_service(repo, clock, monkeypatch, lambda y, m, market: good if market == 'sii' else [])
    svc.refresh(now=clock)
    calls = []

    def flaky(year, month, market):
        calls.append(market)
        if len(calls) > 1:
            raise ValueError('MOPS 回應不是法說會彙總表')
        return []

    svc = conference_service(repo, clock, monkeypatch, flaky)
    assert svc.refresh(now=clock)['conferences'] is None
    assert [r['date'] for r in repo.read(['2330.TW'], clock.date(), date.max)
            if r['type'] == service.CONFERENCE_TYPE] == [day]


def test_migration_is_additive_and_repeatable(repo):
    db = repo.db
    db._ensure_calendar_event_schema()
    assert 'calendar_events' in inspect(db._engine).get_table_names()
    with db.get_session() as s:
        assert s.execute(select(DatabaseSchemaMigration).where(
            DatabaseSchemaMigration.version == '2026-11-01-calendar-events')).scalar_one()


def test_cache_filters_scope_staleness_and_unknown(repo, clock):
    svc = service.CalendarService(repo, lambda: {'AAPL': 'Apple', '2330.TW': '台積電'})
    repo.save_earnings(row(clock))
    repo.save_earnings(row(clock, 'MSFT'))
    got = svc.events(clock.date(), clock.date() + timedelta(days=30), now=clock)
    assert [r['code'] for r in got['events'] if r['code']] == ['AAPL']
    assert [r['code'] for r in got['undated']] == ['2330.TW']
    assert svc.next_earnings('AAPL', clock)['date'] == (clock + timedelta(days=3)).date()
    repo.save_earnings(row(clock, updated_at=(clock - timedelta(days=4)).replace(tzinfo=None)))
    got = svc.events(clock.date(), clock.date() + timedelta(days=30), now=clock)
    assert all(r['code'] is None for r in got['events'])
    assert len(got['undated']) == 2 and svc.next_earnings('AAPL', clock) is None


def test_out_of_range_future_is_not_undated_and_removed_members_hidden(repo, clock):
    repo.save_earnings(row(clock, days=60))
    svc = service.CalendarService(repo, lambda: {'AAPL': 'Apple'})
    got = svc.events(clock.date(), clock.date() + timedelta(days=5), now=clock)
    assert not got['undated'] and all(r['code'] is None for r in got['events'])
    assert svc.events(clock.date(), clock.date() + timedelta(days=90), code='MSFT', now=clock) == {
        'events': [], 'undated': [], 'cache_updated_at': None}


def test_reschedule_and_no_date_clear_old_future(repo, clock, monkeypatch):
    svc = service.CalendarService(repo, lambda: {'AAPL': 'Apple', 'MSFT': 'Microsoft'})
    monkeypatch.setattr(svc, '_refresh_macro', lambda now: None)
    monkeypatch.setattr(service, 'fetch_earnings', lambda c, d: None if c == 'AAPL' else row(clock, 'MSFT', days=9))
    repo.save_earnings(row(clock))
    stats = svc.refresh(clock)
    assert stats == {'updated': 1, 'undated': 1, 'failed': 0, 'conferences': 0}
    assert svc.next_earnings('AAPL', clock) is None
    assert svc.next_earnings('MSFT', clock)['date'] == (clock + timedelta(days=9)).date()

    def broken(c, d):
        raise RuntimeError('both sources down')
    monkeypatch.setattr(service, 'fetch_earnings', broken)
    assert svc.refresh(clock)['failed'] == 2
    assert svc.next_earnings('MSFT', clock) is not None


def test_tw_deadlines_are_market_only_and_not_earnings(clock):
    start, end = clock.date(), clock.date() + timedelta(days=366)
    rows = service.local_events(start, end, True)
    deadlines = [r for r in rows if r['date_kind'] == 'statutory_deadline']
    assert deadlines and all(r['code'] is None and r['type'] != 'earnings' for r in deadlines)
    assert all('非個股實際' in r['detail'] and '75日' in r['detail'] for r in deadlines)
    assert not any(r['date_kind'] == 'statutory_deadline' for r in service.local_events(start, end, False))


def test_api_boundaries_and_date_serialization(repo, clock):
    app = FastAPI()
    app.include_router(router, prefix='/api/v1/calendar')
    svc = service.CalendarService(repo, lambda: {'BRK.B': 'Berkshire'})
    repo.save_earnings(row(clock, 'BRK.B'))
    app.dependency_overrides[get_calendar_service] = lambda: svc
    client = Client(app)
    params = {'from': clock.date().isoformat(), 'to': (clock.date() + timedelta(days=30)).isoformat(), 'code': 'BRK-B'}
    response = client.get('/api/v1/calendar/events', params=params)
    assert response.status_code == 200
    got = response.json()
    assert got['events'][0]['code'] == 'BRK.B' and got['events'][0]['timezone'] == 'America/New_York'
    assert got['events'][0]['date'] == (clock.date() + timedelta(days=3)).isoformat()
    params['to'] = (clock.date() - timedelta(days=1)).isoformat()
    assert client.get('/api/v1/calendar/events', params=params).status_code == 400
    params['to'] = (clock.date() + timedelta(days=367)).isoformat()
    assert client.get('/api/v1/calendar/events', params=params).status_code == 400
    params['from'] = 'invalid'
    assert client.get('/api/v1/calendar/events', params=params).status_code == 422


def test_refresh_worker_is_opt_in_and_independent_of_schedule(monkeypatch):
    assert service.start_calendar_refresh_worker(SimpleNamespace()) is None
    called = threading.Event()
    monkeypatch.setattr(service, 'CalendarService', lambda: SimpleNamespace(refresh=called.set))
    stop = service.start_calendar_refresh_worker(SimpleNamespace(calendar_refresh_enabled=True, schedule_enabled=False))
    try:
        assert called.wait(5)
    finally:
        stop.set()


def test_nasdaq_down_and_yahoo_empty_keeps_cache(repo, clock, monkeypatch):
    repo.save_earnings(row(clock))
    monkeypatch.setattr(sources, 'nasdaq_json', Mock(side_effect=RuntimeError('503')))
    monkeypatch.setattr(sources, 'yahoo_earnings', lambda c, d: None)
    svc = service.CalendarService(repo, members_provider=lambda: {'AAPL': 'Apple'})
    monkeypatch.setattr(svc, '_refresh_macro', lambda now: None)
    assert svc.refresh(now=clock)['failed'] == 1
    assert repo.read(['AAPL'], clock.date(), date.max)[0]['date'] is not None


def test_analysis_cache_failure_does_not_block_and_all_languages(monkeypatch):
    monkeypatch.setattr(service, 'CalendarService', Mock(side_effect=RuntimeError('storage offline')))
    evidence = service.earnings_evidence('AAPL')
    assert evidence['date'] is None
    for language in ('zh', 'zh-TW', 'en', 'ko'):
        assert 'AAPL' in service.earnings_prompt(evidence, language)


def test_tw_otc_members_and_other_markets_excluded(repo, monkeypatch):
    from src.services.portfolio_service import PortfolioService
    from src.services.system_config_service import SystemConfigService
    monkeypatch.setattr(SystemConfigService, 'get_config', lambda *a, **k: {'items': [
        {'key': 'STOCK_LIST', 'value': '8299.TWO,00679B.TWO,2330.TW,AAPL,7203.T,000660.KS,^GSPC'}]})
    calls = []

    def snapshot(self, **kwargs):
        calls.append(kwargs)
        return {'accounts': [{'positions': [
            {'symbol': '6488.TWO', 'quantity': 2, 'name': '環球晶'},
            {'symbol': 'BRK-B', 'quantity': 3, 'name': 'Berkshire'},
            {'symbol': 'MSFT', 'quantity': 0, 'name': 'sold'},
        ]}]}

    monkeypatch.setattr(PortfolioService, 'get_portfolio_snapshot', snapshot)
    members = service.calendar_members(db=repo.db)
    assert set(members) == {'8299.TWO', '00679B.TWO', '2330.TW', 'AAPL', '6488.TWO', 'BRK.B'}
    assert calls == [{'include_realtime': False, 'read_only': True}]


def test_earnings_reaches_legacy_and_agent_messages(clock, monkeypatch):
    from tests.litellm_stub import ensure_litellm_stub
    ensure_litellm_stub()
    from tests.test_analyzer_prompt_language import _make_analyzer, _rich_context
    from src.agent.executor import AgentExecutor
    from src.agent.orchestrator import AgentOrchestrator
    from src.agent.agents.base_agent import BaseAgent

    evidence = {'code': 'AAPL', 'date': (clock.date() + timedelta(days=3)).isoformat(),
                'status': 'estimated', 'timezone': 'America/New_York'}
    prompt = service.earnings_prompt(evidence, 'zh-TW')
    context = _rich_context()
    context['next_earnings'] = evidence
    analyzer = _make_analyzer(legacy=True)
    monkeypatch.setattr('src.analyzer.get_config', lambda: SimpleNamespace(news_max_age_days=3, news_strategy_profile='short'))
    assert prompt in analyzer._format_prompt(context, 'Apple', report_language='zh-TW')
    initial = {'stock_code': 'AAPL', 'report_language': 'zh-TW', 'next_earnings': evidence, 'earnings_prompt': prompt}
    assert prompt in AgentExecutor.__new__(AgentExecutor)._build_user_message('analyze', initial)
    ctx = AgentOrchestrator.__new__(AgentOrchestrator)._build_context('analyze', initial)

    class Reader(BaseAgent):
        def system_prompt(self, ctx):
            return 'system'

        def build_user_message(self, ctx):
            return 'user'

    reader = Reader.__new__(Reader)
    reader._build_memory_context = lambda ctx: ''
    assert prompt in '\n'.join(m['content'] for m in reader._build_messages(ctx))


def test_past_earnings_remains_visible_but_next_date_is_unknown(repo, clock):
    # 財報當日刷新，次日跨過美東午夜後仍在三日鮮度內。
    repo.save_earnings(row(clock, days=-1, updated_at=(clock - timedelta(days=1)).replace(tzinfo=None)))
    svc = service.CalendarService(repo, lambda: {'AAPL': 'Apple'})
    got = svc.events(clock.date() - timedelta(days=2), clock.date() + timedelta(days=7), now=clock)
    assert any(r['code'] == 'AAPL' for r in got['events'])
    assert [r['code'] for r in got['undated']] == ['AAPL']
    assert svc.next_earnings('AAPL', clock) is None


def test_earnings_today_still_known_in_source_timezone(repo, clock):
    local_today = clock.astimezone(service.ET).date()
    repo.save_earnings(row(clock, date=local_today))
    svc = service.CalendarService(repo, lambda: {'AAPL': 'Apple'})
    got = svc.events(local_today, local_today + timedelta(days=7), now=clock)
    assert not got['undated'] and svc.next_earnings('AAPL', clock) is not None
