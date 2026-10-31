import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Pencil, Plus, RefreshCw, Search, Trash2 } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { fundsApi } from '../api/funds';
import type { ParsedApiError } from '../api/error';
import { getParsedApiError } from '../api/error';
import {
  ApiErrorAlert,
  AppPage,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  InlineAlert,
  Input,
  Loading,
  PageHeader,
} from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type { UiTextKey } from '../i18n/uiText';
import { getIntlLocale } from '../i18n/intlLocale';
import type {
  FundDetail,
  FundHoldingItem,
  FundHoldingListResponse,
  FundNavPeriod,
  FundNavPoint,
  FundReturns,
  FundSearchItem,
  FundTopHoldingsResponse,
} from '../types/funds';
import { formatSignedPct, getTodayIso } from '../utils/portfolioFormat';
import { cn } from '../utils/cn';
import { marketToneClass } from '../utils/marketTone';

const changeClass = (value?: number | null): string => marketToneClass(value);

type RangeKey = 'm1' | 'm3' | 'm6' | 'y1' | 'y3' | 'y5' | 'all';
// 區間走勢交給後端用報酬卡同一個基準點切（period），首尾相除才會等於同頁的「近N」報酬；all 不切
const RANGE_PERIOD: Record<RangeKey, FundNavPeriod | undefined> = {
  m1: 'm1', m3: 'm3', m6: 'm6', y1: 'y1', y3: 'y3', y5: 'y5', all: undefined,
};
const RANGES: RangeKey[] = ['m1', 'm3', 'm6', 'y1', 'y3', 'y5', 'all'];
const RETURN_KEYS: (keyof FundReturns)[] = ['w1', 'm1', 'm3', 'm6', 'ytd', 'y1', 'y3', 'y5'];

type HoldingForm = {
  id?: number;
  fundId: string;
  fundName: string;
  units: string;
  costTotal: string;
  asOf: string;
  platform: string;
  note: string;
};

const emptyForm = (fund?: { fundId: string; name: string }): HoldingForm => ({
  fundId: fund?.fundId ?? '',
  fundName: fund?.name ?? '',
  units: '',
  costTotal: '',
  asOf: getTodayIso(),
  platform: '',
  note: '',
});

const FundsPage: React.FC = () => {
  const { t, language } = useUiLanguage();
  const locale = getIntlLocale(language);
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get('fund');

  const [query, setQuery] = useState('');
  const [results, setResults] = useState<FundSearchItem[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [holdings, setHoldings] = useState<FundHoldingListResponse | null>(null);
  const [detail, setDetail] = useState<FundDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [points, setPoints] = useState<FundNavPoint[]>([]);
  const [range, setRange] = useState<RangeKey>('y1');
  const [top, setTop] = useState<FundTopHoldingsResponse | null>(null);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [form, setForm] = useState<HoldingForm | null>(null);
  const [saving, setSaving] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<FundHoldingItem | null>(null);

  const num = useCallback(
    (value: number | null | undefined, digits = 2) =>
      value == null || Number.isNaN(value)
        ? '—'
        : value.toLocaleString(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits }),
    [locale],
  );
  const pct = (value: number | null | undefined) => (value == null ? '—' : formatSignedPct(value));

  const loadHoldings = useCallback(async () => {
    try {
      setHoldings(await fundsApi.listHoldings());
    } catch (err) {
      setError(getParsedApiError(err));
    }
  }, []);

  useEffect(() => {
    void loadHoldings();
  }, [loadHoldings]);

  const selectFund = useCallback(
    (fundId: string) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set('fund', fundId);
        return next;
      });
    },
    [setSearchParams],
  );

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setTop(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setTop(null);
    fundsApi
      .getDetail(selectedId)
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setDetail(null);
          setError(getParsedApiError(err));
        }
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    fundsApi
      .getTopHoldings(selectedId)
      .then((data) => {
        if (!cancelled) setTop(data);
      })
      .catch(() => {
        if (!cancelled) setTop({ fundId: selectedId, items: [], error: 'source_unavailable' });
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  // 「新增持倉」表單開著但還沒選基金時，選定的基金載完就帶入；已有基金的表單（含編輯中）不動
  useEffect(() => {
    if (!detail) return;
    setForm((prev) => (prev && !prev.fundId ? { ...prev, fundId: detail.fundId, fundName: detail.name } : prev));
  }, [detail]);

  // 詳情載完（含首次補歷史）才抓走勢，避免與補歷史搶先回空
  useEffect(() => {
    if (!detail) {
      setPoints([]);
      return;
    }
    let cancelled = false;
    fundsApi
      .getNavHistory(detail.fundId, { period: RANGE_PERIOD[range] })
      .then((data) => {
        if (!cancelled) setPoints(data.points);
      })
      .catch((err) => {
        if (!cancelled) setError(getParsedApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [detail, range]);

  const runSearch = async (event?: React.FormEvent) => {
    event?.preventDefault();
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    try {
      setResults((await fundsApi.search(q)).items);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setSearching(false);
    }
  };

  const saveForm = async () => {
    if (!form) return;
    const units = Number(form.units);
    const costTotal = Number(form.costTotal);
    if (!form.fundId || !(units > 0) || !(costTotal >= 0) || !form.asOf) return;
    setSaving(true);
    try {
      if (form.id != null) {
        await fundsApi.updateHolding(form.id, {
          units, costTotal, asOf: form.asOf, platform: form.platform, note: form.note,
        });
      } else {
        await fundsApi.createHolding({
          fundId: form.fundId, units, costTotal, asOf: form.asOf, platform: form.platform, note: form.note || undefined,
        });
      }
      setForm(null);
      await loadHoldings();
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    try {
      await fundsApi.deleteHolding(pendingDelete.id);
      await loadHoldings();
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setPendingDelete(null);
    }
  };

  const chartUp = points.length > 1 && points[points.length - 1].nav >= points[0].nav;
  const rangeChange = points.length > 1 ? (points[points.length - 1].nav / points[0].nav - 1) * 100 : null;
  const heldIds = useMemo(() => new Set(holdings?.items.map((h) => h.fundId) ?? []), [holdings]);

  const editHolding = (h: FundHoldingItem) =>
    setForm({
      id: h.id, fundId: h.fundId, fundName: h.fundName, units: String(h.units),
      costTotal: String(h.costTotal), asOf: h.asOf, platform: h.platform, note: h.note ?? '',
    });

  const rowActions = (h: FundHoldingItem) => (
    <>
      <Button variant="ghost" size="xsm" aria-label={t('funds.holdings.edit')} onClick={() => editHolding(h)}>
        <Pencil className="h-4 w-4" />
      </Button>
      <Button variant="ghost" size="xsm" aria-label={t('funds.holdings.delete')} onClick={() => setPendingDelete(h)}>
        <Trash2 className="h-4 w-4" />
      </Button>
    </>
  );

  const holdingsCard = (
    <Card variant="bordered" padding="md">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">{t('funds.holdings.title')}</h2>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => void loadHoldings()} aria-label={t('funds.refresh')}>
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setForm(emptyForm(detail ?? undefined))}>
            <Plus className="mr-1 h-4 w-4" />
            {t('funds.holdings.add')}
          </Button>
        </div>
      </div>
      {holdings?.navError ? <InlineAlert variant="warning" message={t('funds.holdings.navError')} /> : null}
      {!holdings ? (
        <Loading label={t('funds.holdings.title')} />
      ) : holdings.items.length === 0 ? (
        <EmptyState title={t('funds.holdings.empty')} description={t('funds.holdings.emptyHint')} />
      ) : (
        <>
        <ul className="divide-y divide-border/60 text-sm tabular-nums md:hidden">
          {holdings.items.map((h) => (
            <li key={h.id} className="py-2">
              <div className="flex items-start justify-between gap-2">
                <button type="button" className="min-w-0 text-left font-medium" onClick={() => selectFund(h.fundId)}>
                  {h.fundName}
                </button>
                <span className={cn('shrink-0 text-right', changeClass(h.pnl))}>{pct(h.pnlPct)}</span>
              </div>
              <div className="mt-1 flex justify-between text-xs text-secondary-text">
                <span>{t('funds.col.marketValue')} <span className="text-foreground">{num(h.marketValue, 0)}</span></span>
                <span className={changeClass(h.pnl)}>{num(h.pnl, 0)}</span>
              </div>
              <div className="mt-0.5 flex items-center justify-between gap-2">
                <span className={cn('text-xs', h.isStale ? 'text-warning' : 'text-secondary-text')}>
                  {t('funds.col.nav')} {num(h.nav, 2)} · {h.navDate ?? t('funds.noNav')} · {h.platform || '—'}
                </span>
                <span className="shrink-0">{rowActions(h)}</span>
              </div>
            </li>
          ))}
          {holdings.totals.map((total) => (
            <li key={total.currency} className="flex justify-between py-2 font-medium">
              <span>{t('funds.holdings.total', { currency: total.currency })}</span>
              <span className={changeClass(total.pnl)}>{num(total.marketValue, 0)} · {pct(total.pnlPct)}</span>
            </li>
          ))}
        </ul>
        <div className="hidden overflow-x-auto md:block">
          <table className="w-full min-w-[720px] text-sm tabular-nums">
            <thead className="text-left text-xs text-secondary-text">
              <tr>
                <th className="py-2 pr-3 font-medium">{t('funds.col.fund')}</th>
                <th className="py-2 pr-3 font-medium">{t('funds.col.platform')}</th>
                <th className="py-2 pr-3 text-right font-medium">{t('funds.col.units')}</th>
                <th className="py-2 pr-3 text-right font-medium">{t('funds.col.nav')}</th>
                <th className="py-2 pr-3 text-right font-medium">{t('funds.col.marketValue')}</th>
                <th className="py-2 pr-3 text-right font-medium">{t('funds.col.cost')}</th>
                <th className="py-2 pr-3 text-right font-medium">{t('funds.col.pnl')}</th>
                <th className="py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {holdings.items.map((h) => (
                <tr key={h.id} className="border-t border-border/60">
                  <td className="py-2 pr-3">
                    <button type="button" className="text-left hover:text-[hsl(var(--primary))]" onClick={() => selectFund(h.fundId)}>
                      {h.fundName}
                    </button>
                    <div className="text-xs text-secondary-text">{t('funds.holdings.asOf', { date: h.asOf })}</div>
                  </td>
                  <td className="py-2 pr-3 text-secondary-text">{h.platform || '—'}</td>
                  <td className="py-2 pr-3 text-right">{num(h.units, 2)}</td>
                  <td className="py-2 pr-3 text-right">
                    {num(h.nav, 2)}
                    <div className={cn('text-xs', h.isStale ? 'text-warning' : 'text-secondary-text')}>
                      {h.navDate ?? t('funds.noNav')}
                    </div>
                  </td>
                  <td className="py-2 pr-3 text-right">{num(h.marketValue, 0)}</td>
                  <td className="py-2 pr-3 text-right">{num(h.costTotal, 0)}</td>
                  <td className={cn('py-2 pr-3 text-right', changeClass(h.pnl))}>
                    {num(h.pnl, 0)}
                    <div className="text-xs">{pct(h.pnlPct)}</div>
                  </td>
                  <td className="py-2 text-right whitespace-nowrap">{rowActions(h)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              {holdings.totals.map((total) => (
                <tr key={total.currency} className="border-t border-border font-medium">
                  <td className="py-2 pr-3" colSpan={4}>
                    {t('funds.holdings.total', { currency: total.currency })}
                  </td>
                  <td className="py-2 pr-3 text-right">{num(total.marketValue, 0)}</td>
                  <td className="py-2 pr-3 text-right">{num(total.costTotal, 0)}</td>
                  <td className={cn('py-2 pr-3 text-right', changeClass(total.pnl))}>
                    {num(total.pnl, 0)}
                    <div className="text-xs">{pct(total.pnlPct)}</div>
                  </td>
                  <td />
                </tr>
              ))}
            </tfoot>
          </table>
        </div>
        </>
      )}
      {form ? (
        <div className="mt-4 space-y-3 rounded-xl border border-border p-3">
          <div className="text-sm font-medium">
            {form.id != null ? t('funds.holdings.edit') : t('funds.holdings.add')}
            {form.fundName ? `：${form.fundName}` : ''}
          </div>
          {!form.fundId ? <InlineAlert variant="info" message={t('funds.holdings.pickFund')} /> : null}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Input label={t('funds.col.units')} type="number" min="0" step="any" value={form.units}
              onChange={(e) => setForm({ ...form, units: e.target.value })} />
            <Input label={t('funds.form.costTotal')} type="number" min="0" step="any" value={form.costTotal}
              onChange={(e) => setForm({ ...form, costTotal: e.target.value })} />
            <Input label={t('funds.form.asOf')} type="date" value={form.asOf}
              onChange={(e) => setForm({ ...form, asOf: e.target.value })} />
            <Input label={t('funds.col.platform')} maxLength={64} value={form.platform}
              onChange={(e) => setForm({ ...form, platform: e.target.value })} />
            <Input label={t('funds.form.note')} maxLength={255} value={form.note}
              onChange={(e) => setForm({ ...form, note: e.target.value })} />
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={() => void saveForm()} disabled={saving || !form.fundId}>
              {t('funds.form.save')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setForm(null)}>
              {t('funds.form.cancel')}
            </Button>
          </div>
        </div>
      ) : null}
    </Card>
  );

  const searchCard = (
    <Card variant="bordered" padding="md">
      <form className="flex gap-2" onSubmit={(e) => void runSearch(e)}>
        <div className="flex-1">
          <Input
            aria-label={t('funds.search.placeholder')}
            placeholder={t('funds.search.placeholder')}
            maxLength={64}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <Button type="submit" size="md" disabled={searching || !query.trim()}>
          <Search className="mr-1 h-4 w-4" />
          {t('funds.search.submit')}
        </Button>
      </form>
      {results ? (
        results.length === 0 ? (
          <div className="mt-3 text-sm text-secondary-text">{t('funds.search.empty')}</div>
        ) : (
          <ul className="mt-3 divide-y divide-border/60">
            {results.map((item) => (
              <li key={item.fundId}>
                <button
                  type="button"
                  onClick={() => selectFund(item.fundId)}
                  className={cn(
                    'flex w-full items-center justify-between gap-3 py-2 text-left text-sm hover:bg-hover',
                    item.fundId === selectedId && 'text-[hsl(var(--primary))]',
                  )}
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{item.name}</span>
                    <span className="block truncate text-xs text-secondary-text">
                      {[item.company, item.typeName, item.currency, item.fundId].filter(Boolean).join(' · ')}
                    </span>
                  </span>
                  <span className="shrink-0 text-right tabular-nums">
                    {num(item.nav, 2)}
                    <span className="block text-xs text-secondary-text">{item.navDate ?? t('funds.noNav')}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )
      ) : (
        <div className="mt-3 text-xs text-secondary-text">{t('funds.search.hint')}</div>
      )}
    </Card>
  );

  const infoRows: [UiTextKey, React.ReactNode][] = detail
    ? [
        ['funds.info.company', detail.company],
        ['funds.info.type', detail.typeName ?? detail.typeCode],
        ['funds.info.area', detail.investArea],
        ['funds.info.currency', detail.currency],
        ['funds.info.inception', detail.inceptionDate],
        ['funds.info.aum', detail.aum != null ? `${num(detail.aum / 1e8, 1)} ${t('funds.info.hundredMillion')} ${detail.aumCurrency ?? ''}（${detail.aumDate ?? '—'}）` : null],
        ['funds.info.dividend', detail.dividendPolicy],
        ['funds.info.isin', detail.isin],
        ['funds.info.fundId', detail.fundId],
      ]
    : [];

  const detailCard = !selectedId ? null : detailLoading && !detail ? (
    <Card variant="bordered" padding="md">
      <Loading label={t('funds.detail.loading')} />
    </Card>
  ) : detail ? (
    <Card variant="bordered" padding="md">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold">{detail.name}</h2>
          <div className="text-xs text-secondary-text">{[detail.company, detail.typeName].filter(Boolean).join(' · ')}</div>
        </div>
        <div className="text-right tabular-nums">
          <div className="text-2xl font-semibold">{num(detail.nav, 2)}</div>
          <div className={cn('text-sm', changeClass(detail.navChangePct))}>
            {detail.navChange != null ? `${detail.navChange > 0 ? '+' : ''}${num(detail.navChange, 2)}` : '—'}{' '}
            ({pct(detail.navChangePct)})
          </div>
          <div className={cn('text-xs', detail.isStale ? 'text-warning' : 'text-secondary-text')}>
            {t('funds.detail.navDate', { date: detail.navDate ?? '—' })}
          </div>
        </div>
      </div>
      {detail.isStale ? <InlineAlert className="mt-3" variant="warning" message={t('funds.detail.stale')} /> : null}
      {detail.historyError ? <InlineAlert className="mt-3" variant="warning" message={t('funds.detail.historyError')} /> : null}
      {!heldIds.has(detail.fundId) ? (
        <div className="mt-3">
          <Button size="sm" variant="secondary" onClick={() => setForm(emptyForm(detail))}>
            <Plus className="mr-1 h-4 w-4" />
            {t('funds.detail.addHolding')}
          </Button>
        </div>
      ) : null}

      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
        {RETURN_KEYS.map((key) => (
          <div key={key} className="rounded-lg border border-border/60 p-2 text-center">
            <div className="text-xs text-secondary-text">{t(`funds.return.${key}` as UiTextKey)}</div>
            <div className={cn('text-sm font-medium tabular-nums', changeClass(detail.returns[key]))}>{pct(detail.returns[key])}</div>
          </div>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-secondary-text">
        <span>{t('funds.risk.drawdown')}：<span className="tabular-nums text-foreground">{pct(detail.risk.maxDrawdown)}</span></span>
        <span>{t('funds.risk.volatility')}：<span className="tabular-nums text-foreground">{detail.risk.volatility == null ? '—' : `${num(detail.risk.volatility, 1)}%`}</span></span>
        <span>{t('funds.returns.note')}</span>
      </div>

      <div className="mt-4">
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setRange(r)}
              className={cn(
                'rounded-md border px-2.5 py-0.5 text-xs',
                r === range
                  ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]'
                  : 'border-border text-secondary-text hover:bg-hover',
              )}
            >
              {t(`funds.range.${r}` as UiTextKey)}
            </button>
          ))}
          {rangeChange != null ? (
            <span className={cn('ml-2 text-xs tabular-nums', changeClass(rangeChange))}>{formatSignedPct(rangeChange)}</span>
          ) : null}
        </div>
        {points.length === 0 ? (
          <div className="py-10 text-center text-xs text-secondary-text">{t('funds.chart.empty')}</div>
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'hsl(var(--secondary-text))' }} axisLine={false} tickLine={false} height={18} minTickGap={48} />
              <YAxis domain={['auto', 'auto']} width={56} tick={{ fontSize: 11 }} tickFormatter={(v) => Number(v).toFixed(0)} />
              <Tooltip
                formatter={(v) => [Number(v).toFixed(2), t('funds.col.nav')]}
                contentStyle={{
                  background: 'hsl(var(--popover))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: 8,
                  fontSize: 12,
                  padding: '6px 10px',
                }}
                labelStyle={{ color: 'hsl(var(--foreground))', fontWeight: 600, marginBottom: 2 }}
                itemStyle={{ color: 'hsl(var(--foreground))' }}
              />
              <Line type="monotone" dataKey="nav" dot={false} strokeWidth={1.5} stroke={chartUp ? '#ef4444' : '#10b981'} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          {infoRows.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="text-secondary-text">{t(key)}</dt>
              <dd className="min-w-0 break-words">{value || '—'}</dd>
            </div>
          ))}
        </dl>
        <div>
          <div className="mb-1 text-sm font-medium">{t('funds.top.title')}</div>
          {!top ? (
            <div className="text-xs text-secondary-text">{t('funds.detail.loading')}</div>
          ) : top.items.length === 0 ? (
            <div className="text-xs text-secondary-text">{t(top.error === 'not_mapped' ? 'funds.top.notMapped' : 'funds.top.unavailable')}</div>
          ) : (
            <table className="w-full text-sm tabular-nums">
              <tbody>
                {top.items.map((item, idx) => (
                  <tr key={`${item.name}-${idx}`} className="border-t border-border/60">
                    <td className="py-1 pr-2">{item.name ?? '—'}</td>
                    <td className="py-1 pr-2 text-xs text-secondary-text">{item.sector ?? ''}</td>
                    <td className="py-1 text-right">{item.weight == null ? '—' : `${num(item.weight, 2)}%`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="mt-1 text-xs text-secondary-text">{t('funds.top.source')}</div>
        </div>
      </div>
      <div className="mt-3 text-xs text-secondary-text">{t('funds.detail.source', { points: String(detail.historyPoints), start: detail.historyStart ?? '—' })}</div>
    </Card>
  ) : null;

  return (
    <AppPage className="space-y-5">
      <PageHeader title={t('funds.title')} description={t('funds.description')} />
      {error ? <ApiErrorAlert error={error} onDismiss={() => setError(null)} /> : null}
      {holdingsCard}
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        {searchCard}
        {detailCard ?? (
          <Card variant="bordered" padding="md">
            <EmptyState title={t('funds.detail.none')} description={t('funds.search.hint')} />
          </Card>
        )}
      </div>
      <ConfirmDialog
        isOpen={pendingDelete != null}
        title={t('funds.holdings.delete')}
        message={t('funds.holdings.deleteConfirm', { name: pendingDelete?.fundName ?? '' })}
        isDanger
        onConfirm={() => void confirmDelete()}
        onCancel={() => setPendingDelete(null)}
      />
    </AppPage>
  );
};

export default FundsPage;
