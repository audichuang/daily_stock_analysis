import { formatUiText } from '../i18n/uiText';
import type { DataCenterText as Text } from '../locales/dataCenterText';
import type { DataDatasetQuality } from '../types/dataCapability';

export const FOCUS_MARKETS = ['tw', 'us'];
const MARKET_ORDER = ['tw', 'us', 'hk', 'cn', 'jp', 'kr'];
const MARKET_DATASETS = ['quote.realtime', 'kline.daily', 'index.daily', 'financial.snapshot', 'market.overview'];

export interface DataRow {
  id: string;
  /** 後端 coverage 的鍵，例如 tw、cn.index.csi；非市場資料為 null。 */
  marketKey: string | null;
  root: string | null;
  dataset: string;
  status: string;
  source: string | null;
  fallbackFrom: string[];
  dataDate: string | null;
  expectedDate: string | null;
  lastSuccess: string | null;
  reason: string | null;
}

export const rowLabel = (row: DataRow, text: Text): string => {
  const dataset = text.datasets[row.dataset] ?? row.dataset;
  if (!row.marketKey) return dataset;
  return `${text.markets[row.marketKey] ?? row.marketKey} ${dataset}`;
};

interface CoverageEntry {
  status?: string;
  source?: string | null;
  fallback_from?: string[];
}

const coverageOf = (dataset: DataDatasetQuality): Array<[string, CoverageEntry]> => {
  const markets = dataset.coverage?.markets;
  if (!markets || typeof markets !== 'object' || Array.isArray(markets)) return [];
  return Object.entries(markets as Record<string, CoverageEntry>);
};

/**
 * Status of a row that carries the dataset's stored date. A source being reachable does not mean
 * the data is fresh (isCurrent false → stale); conversely, data already current means the row is
 * fine even if no source has been probed yet (unknown → ok).
 */
const datedStatus = (dataset: DataDatasetQuality, status: string): string => {
  if (dataset.isCurrent === false) return 'stale';
  if (dataset.isCurrent === true && dataset.dataDate && status === 'unknown') return 'ok';
  return status;
};

const marketRowsOf = (dataset: DataDatasetQuality): DataRow[] => {
  const entries = coverageOf(dataset);
  // 整個資料集被關掉時沒有 coverage；展開到台股美股，結論才看得到。
  const expanded: Array<[string, CoverageEntry]> = entries.length > 0
    ? [...entries]
    : FOCUS_MARKETS.map((market): [string, CoverageEntry] => [
      market,
      { status: dataset.status, source: dataset.source, fallback_from: dataset.fallbackFrom },
    ]);
  // 資料日期是資料庫實際的最新日；來源路由沒列到該市場（台股指數）也要有一列，否則過期看不到。
  if (dataset.dataMarket && !expanded.some(([key]) => key === dataset.dataMarket)) {
    expanded.push([dataset.dataMarket, { status: dataset.isCurrent ? 'ok' : 'unknown', source: null, fallback_from: [] }]);
  }
  return expanded.map(([key, entry]) => {
    const dated = key === dataset.dataMarket;
    const status = dated ? datedStatus(dataset, entry.status ?? 'unknown') : entry.status ?? 'unknown';
    return {
      id: `${dataset.dataset}:${key}`,
      marketKey: key,
      root: key.split('.')[0],
      dataset: dataset.dataset,
      status,
      source: entry.source ?? null,
      fallbackFrom: entry.fallback_from ?? [],
      dataDate: dated ? dataset.dataDate ?? null : null,
      expectedDate: dated ? dataset.expectedDate ?? null : null,
      lastSuccess: dataset.dataset === 'quote.realtime' ? dataset.lastSuccess ?? null : null,
      reason: dataset.reason ?? null,
    };
  });
};

const orderIndex = (list: string[], value: string | null): number => {
  const index = list.indexOf(value ?? '');
  return index === -1 ? list.length : index;
};

/** 全部市場列，台股、美股在前；同市場依資料集固定順序。 */
export const buildMarketRows = (datasets: DataDatasetQuality[]): DataRow[] => datasets
  .filter((dataset) => MARKET_DATASETS.includes(dataset.dataset) || coverageOf(dataset).length > 0)
  .flatMap(marketRowsOf)
  .map((row, index) => ({ row, index }))
  .sort((a, b) => (
    orderIndex(MARKET_ORDER, a.row.root) - orderIndex(MARKET_ORDER, b.row.root)
    || orderIndex(MARKET_DATASETS, a.row.dataset) - orderIndex(MARKET_DATASETS, b.row.dataset)
    || a.index - b.index
  ))
  .map(({ row }) => row);

export const buildSystemRows = (datasets: DataDatasetQuality[]): DataRow[] => datasets
  .filter((dataset) => !MARKET_DATASETS.includes(dataset.dataset) && coverageOf(dataset).length === 0)
  .map((dataset) => ({
    id: dataset.dataset,
    marketKey: null,
    root: null,
    dataset: dataset.dataset,
    status: dataset.stale === true ? 'stale' : datedStatus(dataset, dataset.status),
    source: dataset.source ?? null,
    fallbackFrom: dataset.fallbackFrom,
    dataDate: dataset.dataDate ?? null,
    expectedDate: dataset.expectedDate ?? null,
    lastSuccess: dataset.lastSuccess ?? null,
    reason: dataset.reason ?? null,
  }));

export type DatasetBucket = 'ok' | 'unchecked' | 'off' | 'issue';

/** Bucket of one table row; the stat cards count these same rows so the numbers add up to the table. */
export const rowBucket = (row: DataRow): DatasetBucket => {
  if (row.reason || row.status === 'unconfigured') return 'off';
  // partial still serves data, so it is not an issue.
  if (row.status === 'ok' || row.status === 'partial') return 'ok';
  if (row.status === 'unknown') return 'unchecked';
  return 'issue';
};

export const countRows = (rows: DataRow[]): Record<DatasetBucket, number> => {
  const counts: Record<DatasetBucket, number> = { ok: 0, unchecked: 0, off: 0, issue: 0 };
  for (const row of rows) counts[rowBucket(row)] += 1;
  return counts;
};

export interface Conclusion {
  /** 'note' is a one-line muted remark, not a banner (only unchecked rows, normal after a holiday or restart). */
  variant: 'success' | 'warning' | 'danger' | 'info' | 'note';
  title: string;
  message: string;
}

const MAX_LISTED = 3;

/** 結論只看台股、美股；其他市場的缺口不該讓首屏變紅。 */
export const buildConclusion = (rows: DataRow[], asOfText: string, text: Text): Conclusion => {
  const focus = rows.filter((row) => row.root && FOCUS_MARKETS.includes(row.root));
  const checked = formatUiText(text.bannerChecked, { time: asOfText });
  if (focus.length === 0) return { variant: 'info', title: text.bannerEmpty, message: checked };

  const off = focus.filter((row) => row.reason || row.status === 'unconfigured');
  const active = focus.filter((row) => !off.includes(row));
  const down = active.filter((row) => row.status === 'unavailable' || row.status === 'cooldown' || row.status === 'unsupported');
  const stale = active.filter((row) => row.status === 'stale');
  const fallback = active.filter((row) => row.status === 'degraded' || row.status === 'partial');
  const unchecked = active.filter((row) => row.status === 'unknown');
  const label = (template: string, row: DataRow) => formatUiText(template, { label: rowLabel(row, text) });
  const items = [
    ...down.map((row) => label(text.isDown, row)),
    ...stale.map((row) => formatUiText(text.stoppedAt, {
      label: rowLabel(row, text),
      date: row.dataDate ?? '—',
      expected: row.expectedDate ?? '—',
    })),
    ...off.map((row) => label(text.isOff, row)),
    ...fallback.map((row) => label(text.viaFallback, row)),
    ...unchecked.map((row) => label(text.isUnchecked, row)),
  ];
  // Most severe first; past three the rest collapse into a total ("A、B、C 等 5 項") so the banner stays short.
  const listed = items.slice(0, MAX_LISTED).join('、');
  const message = items.length > MAX_LISTED ? `${listed} ${formatUiText(text.andMore, { count: items.length })}` : listed;

  if (down.length > 0) return { variant: 'danger', title: text.bannerDown, message };
  if (stale.length > 0) return { variant: 'warning', title: text.bannerStale, message };
  if (off.length > 0 || fallback.length > 0) return { variant: 'warning', title: text.bannerAttention, message };
  if (unchecked.length > 0) {
    return { variant: 'note', title: text.bannerUnchecked, message: formatUiText(text.uncheckedNote, { count: unchecked.length }) };
  }

  const dated = focus.find((row) => row.dataDate);
  return {
    variant: 'success',
    title: text.bannerOk,
    message: dated?.dataDate
      ? formatUiText(text.bannerDataDate, { label: rowLabel(dated, text), date: dated.dataDate })
      : checked,
  };
};

const scopeLabel = (scope: string, text: Text): string | null => text.markets[scope] ?? text.scenarios[scope] ?? null;

/** 後端警告碼（可帶市場或場景前綴）翻成中文並合併；認不得的只計數，原文留給技術細節。 */
export const translateWarnings = (codes: string[], text: Text): { messages: string[]; unknownCount: number } => {
  const scopesByMessage = new Map<string, string[]>();
  let unknownCount = 0;
  for (const code of new Set(codes)) {
    let rest = code;
    let scope: string | null = null;
    const separator = code.indexOf(':');
    if (separator > 0) {
      const head = scopeLabel(code.slice(0, separator), text);
      if (head) {
        scope = head;
        rest = code.slice(separator + 1);
      }
    }
    const parts = rest.split(':');
    let message: string | undefined;
    if (parts[0] === 'source_status' && parts.length === 3) {
      message = formatUiText(text.warnSourceStatus, { source: parts[1], status: text.status[parts[2]] ?? parts[2] });
    } else if (parts[0] === 'unknown_source' && parts.length === 2) {
      message = formatUiText(text.warnUnknownSource, { source: parts[1] });
    } else {
      message = text.warnings[rest] ?? text.reasons[rest];
    }
    if (!message) {
      unknownCount += 1;
      continue;
    }
    const scopes = scopesByMessage.get(message) ?? [];
    if (scope && !scopes.includes(scope)) scopes.push(scope);
    scopesByMessage.set(message, scopes);
  }
  return {
    messages: Array.from(scopesByMessage, ([message, scopes]) => (scopes.length ? `${scopes.join('、')}：${message}` : message)),
    unknownCount,
  };
};
