import apiClient from './index';
import { toCamelCase } from './utils';

export type UsagePeriod = 'today' | 'month' | 'all';

export type UsageCallTypeBreakdown = {
  callType: string;
  calls: number;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
};

export type UsageModelBreakdown = {
  model: string;
  calls: number;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  maxTotalTokens: number;
};

export type UsageCallRecord = {
  id: number;
  calledAt: string;
  callType: string;
  model: string;
  stockCode?: string | null;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  channel?: string | null;
  billing?: string | null;
  cacheReadTokens?: number | null;
};

export type UsageDayBreakdown = {
  date: string;
  calls: number;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
};

export type UsageChannelBreakdown = {
  channel: string;
  billing: string;
  calls: number;
  totalTokens: number;
};

export type UsageCacheSummary = {
  readTokens: number;
  knownPromptTokens: number;
  /** 0 到 1；沒有任何呼叫回報快取時為 null。 */
  hitRatio: number | null;
};

export type UsageModelCost = {
  model: string;
  channel: string;
  billing: string;
  totalTokens: number;
  estimatedCost: number | null;
};

export type UsageCostSummary = {
  currency: string;
  estimatedTotal: number | null;
  complete: boolean;
  unpricedModels: string[];
  subscriptionTokens: number;
  byModel: UsageModelCost[];
};

export type UsagePreviousPeriod = {
  fromDate: string;
  toDate: string;
  totalCalls: number;
  totalTokens: number;
  estimatedCost: number | null;
  callsChangePct: number | null;
  tokensChangePct: number | null;
  costChangePct: number | null;
};

export type UsageSort = 'newest' | 'oldest' | 'tokens';

export type UsageDashboard = {
  period: UsagePeriod;
  fromDate: string;
  toDate: string;
  totalCalls: number;
  totalPromptTokens: number;
  totalCompletionTokens: number;
  totalTokens: number;
  byCallType: UsageCallTypeBreakdown[];
  byModel: UsageModelBreakdown[];
  recentCalls: UsageCallRecord[];
  byDay: UsageDayBreakdown[];
  byChannel: UsageChannelBreakdown[];
  cache: UsageCacheSummary;
  cost: UsageCostSummary;
  previous: UsagePreviousPeriod | null;
  recentTotal: number;
};

export type UsageDashboardParams = {
  period?: UsagePeriod;
  limit?: number;
  offset?: number;
  callType?: string;
  sort?: UsageSort;
  day?: string;
};

export const usageApi = {
  getDashboard: async (params: UsageDashboardParams = {}): Promise<UsageDashboard> => {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/usage/dashboard', {
      params: {
        period: params.period ?? 'month',
        limit: params.limit ?? 50,
        ...(params.offset ? { offset: params.offset } : {}),
        ...(params.callType ? { call_type: params.callType } : {}),
        ...(params.sort && params.sort !== 'newest' ? { sort: params.sort } : {}),
        ...(params.day ? { day: params.day } : {}),
      },
    });

    return toCamelCase<UsageDashboard>(response.data);
  },
};
