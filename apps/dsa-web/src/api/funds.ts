import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  FundDetail,
  FundHoldingCreateRequest,
  FundHoldingItem,
  FundHoldingListResponse,
  FundHoldingUpdateRequest,
  FundNavHistoryResponse,
  FundSearchResponse,
  FundTopHoldingsResponse,
} from '../types/funds';

function holdingBody(payload: FundHoldingUpdateRequest & { fundId?: string }): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (payload.fundId !== undefined) body.fund_id = payload.fundId;
  if (payload.units !== undefined) body.units = payload.units;
  if (payload.costTotal !== undefined) body.cost_total = payload.costTotal;
  if (payload.asOf !== undefined) body.as_of = payload.asOf;
  if (payload.platform !== undefined) body.platform = payload.platform;
  if (payload.note !== undefined) body.note = payload.note;
  return body;
}

export const fundsApi = {
  async search(q: string, limit = 20): Promise<FundSearchResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/funds/search', { params: { q, limit } });
    return toCamelCase<FundSearchResponse>(response.data);
  },

  async getDetail(fundId: string): Promise<FundDetail> {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/funds/${encodeURIComponent(fundId)}`);
    return toCamelCase<FundDetail>(response.data);
  },

  async getNavHistory(fundId: string, days?: number): Promise<FundNavHistoryResponse> {
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/funds/${encodeURIComponent(fundId)}/nav`,
      { params: days ? { days } : {} },
    );
    return toCamelCase<FundNavHistoryResponse>(response.data);
  },

  async getTopHoldings(fundId: string): Promise<FundTopHoldingsResponse> {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/funds/${encodeURIComponent(fundId)}/holdings`);
    return toCamelCase<FundTopHoldingsResponse>(response.data);
  },

  async listHoldings(): Promise<FundHoldingListResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/funds/holdings');
    return toCamelCase<FundHoldingListResponse>(response.data);
  },

  async createHolding(payload: FundHoldingCreateRequest): Promise<FundHoldingItem> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/funds/holdings', holdingBody(payload));
    return toCamelCase<FundHoldingItem>(response.data);
  },

  async updateHolding(id: number, payload: FundHoldingUpdateRequest): Promise<FundHoldingItem> {
    const response = await apiClient.put<Record<string, unknown>>(`/api/v1/funds/holdings/${id}`, holdingBody(payload));
    return toCamelCase<FundHoldingItem>(response.data);
  },

  async deleteHolding(id: number): Promise<void> {
    await apiClient.delete(`/api/v1/funds/holdings/${id}`);
  },
};
