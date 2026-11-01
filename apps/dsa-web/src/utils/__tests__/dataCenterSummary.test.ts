import { describe, expect, it } from 'vitest';
import { DATA_CENTER_TEXT } from '../../locales/dataCenterText';
import type { DataDatasetQuality } from '../../types/dataCapability';
import {
  buildConclusion,
  buildMarketRows,
  buildSystemRows,
  countRows,
  FOCUS_MARKETS,
  type DataRow,
} from '../dataCenterSummary';

const text = DATA_CENTER_TEXT['zh-TW'];

// Fixed far-future dates: the summary only compares fields from the API, never the wall clock.
const base: DataDatasetQuality = {
  dataset: 'kline.daily',
  status: 'ok',
  source: null,
  stale: null,
  lastSuccess: null,
  lastError: null,
  fallbackFrom: [],
  coverage: null,
  warnings: [],
  dataDate: null,
  dataMarket: null,
  expectedDate: null,
  isCurrent: null,
  reason: null,
};

const market = (status: string, source: string | null = null) => ({ status, source, fallback_from: [] });

// Mirrors DataCenterPage: the cards count the Taiwan/US table plus the system table.
const visibleRows = (datasets: DataDatasetQuality[]): DataRow[] => [
  ...buildMarketRows(datasets).filter((row) => row.root && FOCUS_MARKETS.includes(row.root)),
  ...buildSystemRows(datasets),
];

const sum = (counts: Record<string, number>) => Object.values(counts).reduce((total, value) => total + value, 0);

describe('countRows', () => {
  it('counts the same rows the tables show, so the cards add up to the row count', () => {
    const datasets: DataDatasetQuality[] = [
      // One dataset, two rows with different states: a per-dataset count would see one "partial" dataset.
      { ...base, dataset: 'kline.daily', status: 'partial', coverage: { markets: { tw: market('ok', 'marketdb'), us: market('unavailable') } } },
      { ...base, dataset: 'quote.realtime', status: 'partial', coverage: { markets: { tw: market('partial', 'shioaji'), us: market('ok', 'yfinance') } } },
      { ...base, dataset: 'news.events', status: 'unknown' },
      { ...base, dataset: 'strategy.screening', status: 'unconfigured', reason: 'screening_disabled' },
    ];
    const rows = visibleRows(datasets);
    const counts = countRows(rows);
    expect(rows).toHaveLength(6);
    expect(sum(counts)).toBe(rows.length);
    // kline tw, realtime tw (partial still serves data), realtime us.
    expect(counts).toEqual({ ok: 3, unchecked: 1, off: 1, issue: 1 });
  });

  it('does not treat a partial row as an issue but still flags a stale one', () => {
    const row = (status: string): DataRow => ({
      id: status, marketKey: 'tw', root: 'tw', dataset: 'kline.daily', status, source: null, fallbackFrom: [],
      dataDate: null, expectedDate: null, lastSuccess: null, reason: null,
    });
    expect(countRows([row('partial')])).toEqual({ ok: 1, unchecked: 0, off: 0, issue: 0 });
    expect(countRows([row('stale')])).toEqual({ ok: 0, unchecked: 0, off: 0, issue: 1 });
  });
});

describe('isCurrent promotion', () => {
  const dated = (overrides: Partial<DataDatasetQuality>): DataDatasetQuality => ({
    ...base,
    dataset: 'index.daily',
    status: 'unknown',
    dataMarket: 'tw',
    dataDate: '2099-03-02',
    expectedDate: '2099-03-02',
    isCurrent: true,
    coverage: { markets: { tw: market('unknown'), us: market('unknown') } },
    ...overrides,
  });
  const twRow = (dataset: DataDatasetQuality) => buildMarketRows([dataset]).find((row) => row.marketKey === 'tw');

  it('promotes a current, dated row whose source was never probed to ok', () => {
    expect(twRow(dated({}))?.status).toBe('ok');
    // The undated sibling row has no evidence and stays unchecked.
    expect(buildMarketRows([dated({})]).find((row) => row.marketKey === 'us')?.status).toBe('unknown');
  });

  it('promotes current, dated system rows too', () => {
    const [row] = buildSystemRows([{ ...base, dataset: 'portfolio.account', status: 'unknown', dataDate: '2099-03-02', isCurrent: true }]);
    expect(row.status).toBe('ok');
  });

  it('leaves the row unchecked without a date or without isCurrent=true', () => {
    expect(twRow(dated({ isCurrent: null }))?.status).toBe('unknown');
    const [undated] = buildSystemRows([{ ...base, dataset: 'portfolio.account', status: 'unknown', isCurrent: true }]);
    expect(undated.status).toBe('unknown');
  });

  it('still marks a dated row stale when the data is behind', () => {
    expect(twRow(dated({ isCurrent: false, dataDate: '2099-02-20' }))?.status).toBe('stale');
  });
});

describe('buildConclusion', () => {
  const row = (id: string, status: string, overrides: Partial<DataRow> = {}): DataRow => ({
    id, marketKey: 'tw', root: 'tw', dataset: id, status, source: null, fallbackFrom: [],
    dataDate: null, expectedDate: null, lastSuccess: null, reason: null, ...overrides,
  });

  it('shows no banner, only a muted note, when the only gap is unchecked rows', () => {
    const conclusion = buildConclusion(
      [row('kline.daily', 'ok'), row('quote.realtime', 'unknown'), row('financial.snapshot', 'unknown', { marketKey: 'us', root: 'us' })],
      '2099-03-02 09:30',
      text,
    );
    expect(conclusion.variant).toBe('note');
    expect(conclusion.message).toBe('2 項尚未被呼叫過，休市或首次啟動時屬正常');
  });

  it('keeps a real banner when something is down, even with unchecked rows', () => {
    const conclusion = buildConclusion([row('quote.realtime', 'unavailable'), row('kline.daily', 'unknown')], 'now', text);
    expect(conclusion.variant).toBe('danger');
  });

  it('lists at most three problems and summarises the rest', () => {
    const rows = ['quote.realtime', 'kline.daily', 'index.daily', 'financial.snapshot', 'market.overview']
      .map((dataset) => row(dataset, 'unavailable'));
    const { message } = buildConclusion(rows, 'now', text);
    expect(message).toBe('台股 即時報價 無法使用、台股 日 K 無法使用、台股 指數日線 無法使用 等 5 項');
    expect(message).not.toContain('財務資料');
  });

  // Seven unchecked Taiwan/US rows plus one unchecked row outside the focus markets (other data).
  const sevenFocusPlusOther = (otherStatus: string): DataRow[] => [
    ...['quote.realtime', 'kline.daily', 'index.daily', 'financial.snapshot'].map((dataset) => row(dataset, 'unknown', { id: `${dataset}:tw` })),
    ...['quote.realtime', 'kline.daily', 'market.overview'].map((dataset) => row(dataset, 'unknown', { id: `${dataset}:us`, marketKey: 'us', root: 'us' })),
    row('news.events', otherStatus, { marketKey: null, root: 'other' }),
  ];

  it('quotes the same unchecked count as the stat card in the muted note', () => {
    const rows = sevenFocusPlusOther('unknown');
    const counted = countRows(rows).unchecked;
    expect(counted).toBe(8);
    const conclusion = buildConclusion(rows, 'now', text, counted);
    expect(conclusion.variant).toBe('note');
    expect(conclusion.message).toContain('8 項');
    expect(conclusion.message).toBe(`${counted} 項尚未被呼叫過，休市或首次啟動時屬正常`);
  });

  it('still judges severity on Taiwan/US only: an unavailable other row does not turn the conclusion red', () => {
    const rows = sevenFocusPlusOther('unavailable');
    const conclusion = buildConclusion(rows, 'now', text, countRows(rows).unchecked);
    expect(conclusion.variant).toBe('note');
    expect(conclusion.variant).not.toBe('danger');
  });
});
