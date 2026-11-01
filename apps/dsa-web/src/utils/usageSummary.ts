import type { UsageCallRecord, UsageCostSummary, UsageModelBreakdown, UsageSort } from '../api/usage';

/** 佔比取到一位小數且加總剛好 100（最大餘數法）；全部為 0 時回 0。 */
export const sharePercents = (values: number[]): number[] => {
  const sum = values.reduce((total, value) => total + value, 0);
  if (sum <= 0) return values.map(() => 0);
  const exact = values.map((value) => (value / sum) * 1000);
  const floors = exact.map(Math.floor);
  const remaining = 1000 - floors.reduce((total, value) => total + value, 0);
  exact
    .map((value, index) => ({ index, remainder: value - floors[index] }))
    .sort((a, b) => b.remainder - a.remainder)
    .slice(0, remaining)
    .forEach(({ index }) => {
      floors[index] += 1;
    });
  return floors.map((value) => value / 10);
};

/** 同一模型會因路由前綴出現多個名稱（openai/x 與 x），顯示時合併。 */
export const modelDisplayName = (model: string): string => model.split('/').pop() || model;

export type ModelCostState = 'priced' | 'partial' | 'unpriced' | 'subscription' | 'unknown';

export interface MergedModel {
  name: string;
  calls: number;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  maxTotalTokens: number;
  cost: number | null;
  costState: ModelCostState;
}

export const mergeModels = (models: UsageModelBreakdown[], cost: UsageCostSummary): MergedModel[] => {
  const merged = new Map<string, MergedModel & { rawModels: Set<string> }>();
  for (const model of models) {
    const name = modelDisplayName(model.model);
    const entry = merged.get(name) ?? {
      name,
      calls: 0,
      promptTokens: 0,
      completionTokens: 0,
      totalTokens: 0,
      maxTotalTokens: 0,
      cost: null,
      costState: 'unknown' as ModelCostState,
      rawModels: new Set<string>(),
    };
    entry.calls += model.calls;
    entry.promptTokens += model.promptTokens;
    entry.completionTokens += model.completionTokens;
    entry.totalTokens += model.totalTokens;
    entry.maxTotalTokens = Math.max(entry.maxTotalTokens, model.maxTotalTokens);
    entry.rawModels.add(model.model);
    merged.set(name, entry);
  }
  return Array.from(merged.values())
    .map(({ rawModels, ...entry }) => {
      const costs = cost.byModel.filter((item) => rawModels.has(item.model));
      const metered = costs.filter((item) => item.billing !== 'subscription');
      const priced = metered.filter((item) => item.estimatedCost != null);
      let costState: ModelCostState = 'unknown';
      if (costs.length > 0 && metered.length === 0) costState = 'subscription';
      else if (metered.length > 0 && priced.length === metered.length) costState = 'priced';
      else if (priced.length > 0) costState = 'partial';
      else if (metered.length > 0) costState = 'unpriced';
      return {
        ...entry,
        costState,
        cost: priced.length > 0 ? priced.reduce((total, item) => total + (item.estimatedCost ?? 0), 0) : null,
      };
    })
    .sort((a, b) => b.totalTokens - a.totalTokens);
};

export type RecordEntry =
  | { kind: 'single'; id: string; record: UsageCallRecord }
  | { kind: 'rounds'; id: string; records: UsageCallRecord[]; promptTokens: number; completionTokens: number; totalTokens: number };

export interface RecordGroup {
  /** 依時間排序才分日；依用量排序時為 null，整批平鋪。 */
  day: string | null;
  entries: RecordEntry[];
}

// 明細沒有 session id：相鄰、同用途同股票同模型、間隔五分鐘內視為同一次的多輪呼叫。
const ROUND_GAP_MS = 5 * 60 * 1000;

const sameRound = (a: UsageCallRecord, b: UsageCallRecord): boolean => {
  if (a.callType !== b.callType || a.model !== b.model || (a.stockCode ?? '') !== (b.stockCode ?? '')) return false;
  const gap = Math.abs(Date.parse(a.calledAt) - Date.parse(b.calledAt));
  return Number.isFinite(gap) && gap <= ROUND_GAP_MS;
};

const toEntry = (records: UsageCallRecord[]): RecordEntry => (records.length === 1
  ? { kind: 'single', id: String(records[0].id), record: records[0] }
  : {
    kind: 'rounds',
    id: `rounds-${records[0].id}`,
    records,
    promptTokens: records.reduce((total, record) => total + record.promptTokens, 0),
    completionTokens: records.reduce((total, record) => total + record.completionTokens, 0),
    totalTokens: records.reduce((total, record) => total + record.totalTokens, 0),
  });

export const groupRecords = (records: UsageCallRecord[], sort: UsageSort): RecordGroup[] => {
  if (sort === 'tokens') {
    return records.length === 0 ? [] : [{ day: null, entries: records.map((record) => toEntry([record])) }];
  }
  const groups: Array<{ day: string; runs: UsageCallRecord[][] }> = [];
  for (const record of records) {
    // called_at 是後端的本地時間字串，與 by_day 同一天界，不經瀏覽器時區換算。
    const day = record.calledAt.slice(0, 10);
    let group = groups[groups.length - 1];
    if (!group || group.day !== day) {
      group = { day, runs: [] };
      groups.push(group);
    }
    const run = group.runs[group.runs.length - 1];
    if (run && sameRound(run[run.length - 1], record)) run.push(record);
    else group.runs.push([record]);
  }
  return groups.map((group) => ({ day: group.day, entries: group.runs.map(toEntry) }));
};
