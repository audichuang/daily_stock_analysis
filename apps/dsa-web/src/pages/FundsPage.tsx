import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeft, Pencil, Plus, RefreshCw, Search, Trash2 } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { fundsApi } from '../api/funds';
import type { ParsedApiError } from '../api/error';
import { getParsedApiError } from '../api/error';
import {
  ApiErrorAlert,
  AppPage,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  DataTable,
  EmptyState,
  IconButton,
  InlineAlert,
  Input,
  Metric,
  MetricGroup,
  PageHeader,
  Segmented,
} from '../components/common';
import { ActionMenu } from '../components/common/ActionMenu';
import type { DataTableColumn, SortState } from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { useMediaQuery } from '../hooks/useMediaQuery';
import { FUNDS_TEXT } from '../locales/fundsText';
import type { UiTextKey } from '../i18n/uiText';
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
import { formatNumber, formatPercent, NO_VALUE } from '../utils/format';
import { fundUnitCost, navAxisDigits } from '../utils/fundChart';
import { getTodayIso } from '../utils/portfolioFormat';
import { cn } from '../utils/cn';
import { marketToneClass } from '../utils/marketTone';

type RangeKey = 'm1' | 'm3' | 'm6' | 'y1' | 'y3' | 'y5' | 'all';
// 區間走勢交給後端用報酬卡同一個基準點切（period），首尾相除才會等於同頁的「近N」報酬；all 不切
const RANGE_PERIOD: Record<RangeKey, FundNavPeriod | undefined> = {
  m1: 'm1', m3: 'm3', m6: 'm6', y1: 'y1', y3: 'y3', y5: 'y5', all: undefined,
};
const RANGES: RangeKey[] = ['m1', 'm3', 'm6', 'y1', 'y3', 'y5', 'all'];
const RETURN_KEYS: (keyof FundReturns)[] = ['w1', 'm1', 'm3', 'm6', 'ytd', 'y1', 'y3', 'y5'];
// Below Tailwind's md breakpoint, same as PageHeader's compact query: the detail becomes a full-screen layer.
const NARROW_QUERY = '(max-width: 767.98px)';

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

type FormErrors = Partial<Record<'units' | 'costTotal' | 'asOf' | 'platform', string>>;

const emptyForm = (fund?: { fundId: string; name: string }): HoldingForm => ({
  fundId: fund?.fundId ?? '',
  fundName: fund?.name ?? '',
  units: '',
  costTotal: '',
  asOf: getTodayIso(),
  platform: '',
  note: '',
});

/** 金額帶正負號；市值與成本不用這個，也不染色。 */
const signedNumber = (value: number | null | undefined, digits = 0): string => {
  if (value == null || !Number.isFinite(value)) return NO_VALUE;
  return `${value > 0 ? '+' : ''}${formatNumber(value, digits)}`;
};

const SectionTitle: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <h3 className="mb-2 text-sm font-semibold text-foreground">{children}</h3>
);

const SkeletonBlock: React.FC<{ className?: string }> = ({ className }) => (
  <div className={cn('animate-pulse rounded-lg bg-border/40', className)} />
);

interface FundSearchBoxProps {
  heldIds: Set<string>;
  onPick: (item: FundSearchItem) => void;
  className?: string;
}

/** 搜尋下拉：頁首與表單共用。名稱完整換行不截尾，已持有的標記出來。 */
const FundSearchBox: React.FC<FundSearchBoxProps> = ({ heldIds, onPick, className }) => {
  const { t } = useUiLanguage();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<FundSearchItem[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!results) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      if (!boxRef.current?.contains(event.target as Node)) setResults(null);
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [results]);

  const runSearch = async (event: React.FormEvent) => {
    event.preventDefault();
    event.stopPropagation();
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setError(null);
    try {
      setResults((await fundsApi.search(q)).items);
    } catch (err) {
      setResults(null);
      setError(getParsedApiError(err));
    } finally {
      setSearching(false);
    }
  };

  return (
    <div ref={boxRef} className={cn('relative', className)}>
      <form className="flex gap-2" onSubmit={(event) => void runSearch(event)}>
        <div className="min-w-0 flex-1">
          <Input
            aria-label={t('funds.search.placeholder')}
            placeholder={t('funds.search.placeholder')}
            title={t('funds.search.hint')}
            maxLength={64}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <Button type="submit" variant="secondary" disabled={searching || !query.trim()}>
          <Search className="h-4 w-4" />
          {t('funds.search.submit')}
        </Button>
      </form>
      {error ? <div className="mt-2"><ApiErrorAlert error={error} onDismiss={() => setError(null)} /></div> : null}
      {results ? (
        <div className="absolute left-0 right-0 z-30 mt-1 max-h-96 overflow-y-auto rounded-[var(--radius-control)] border border-border/70 bg-card p-1 shadow-soft-card md:min-w-[28rem]">
          {results.length === 0 ? (
            <div className="px-2 py-3 text-sm text-secondary-text">{t('funds.search.empty')}</div>
          ) : (
            <ul>
              {results.map((item) => (
                <li key={item.fundId}>
                  <button
                    type="button"
                    onClick={() => {
                      setResults(null);
                      setQuery('');
                      onPick(item);
                    }}
                    className="flex w-full cursor-pointer items-start justify-between gap-3 rounded-[6px] px-2 py-2 text-left text-sm hover:bg-hover"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block break-words font-medium">
                        {item.name}
                        {heldIds.has(item.fundId) ? <Badge variant="info" className="ml-2 align-middle">{t('funds.search.held')}</Badge> : null}
                      </span>
                      <span className="block text-xs text-secondary-text">
                        {[item.company, item.typeName, item.currency, item.fundId].filter(Boolean).join(' · ')}
                      </span>
                    </span>
                    <span className="shrink-0 text-right tabular-nums">
                      {formatNumber(item.nav, 2)}
                      <span className="block text-xs text-secondary-text">{item.navDate ?? t('funds.noNav')}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
};

const FundsPage: React.FC = () => {
  const { t, language } = useUiLanguage();
  const text = FUNDS_TEXT[language];
  const narrow = useMediaQuery(NARROW_QUERY);
  const [searchParams, setSearchParams] = useSearchParams();
  const urlFundId = searchParams.get('fund');
  // 沒帶 ?fund= 時自動選第一檔只放在 state，不寫網址；使用者點選或外部帶參數才寫網址。
  const [autoFundId, setAutoFundId] = useState<string | null>(null);
  const selectedId = urlFundId ?? autoFundId;

  const [holdings, setHoldings] = useState<FundHoldingListResponse | null>(null);
  const [holdingsError, setHoldingsError] = useState<ParsedApiError | null>(null);
  const [detail, setDetail] = useState<FundDetail | null>(null);
  const [detailError, setDetailError] = useState<ParsedApiError | null>(null);
  const [detailReload, setDetailReload] = useState(0);
  const [points, setPoints] = useState<FundNavPoint[]>([]);
  const [navError, setNavError] = useState<ParsedApiError | null>(null);
  const [range, setRange] = useState<RangeKey>('y1');
  const [top, setTop] = useState<FundTopHoldingsResponse | null>(null);
  const [form, setForm] = useState<HoldingForm | null>(null);
  const [formErrors, setFormErrors] = useState<FormErrors>({});
  const [formError, setFormError] = useState<ParsedApiError | null>(null);
  const [saving, setSaving] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<FundHoldingItem | null>(null);
  const [sort, setSort] = useState<SortState>({ key: 'marketValue', direction: 'desc' });
  // 手機的全螢幕詳情層：預設選第一檔不開，使用者點了才開。
  // 帶 ?fund= 進來是明確要看這檔（盯盤基金卡、重新整理）；自動選取發生在掛載之後，不受影響。
  const [mobileDetailOpen, setMobileDetailOpen] = useState(() => urlFundId !== null);
  const mobileLayerOpen = narrow && mobileDetailOpen && selectedId !== null;
  const listRef = useRef<HTMLDivElement>(null);

  const loadHoldings = useCallback(async () => {
    setHoldingsError(null);
    try {
      setHoldings(await fundsApi.listHoldings());
    } catch (err) {
      setHoldingsError(getParsedApiError(err));
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

  // 手機詳情層的返回：選取改存回 state（列表仍選這檔），再把 ?fund= 從網址拿掉，
  // 這樣重新整理或分享網址不會又直接打開詳情層。
  const closeMobileDetail = useCallback(() => {
    if (selectedId) setAutoFundId(selectedId);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete('fund');
      return next;
    }, { replace: true });
    setMobileDetailOpen(false);
  }, [selectedId, setSearchParams]);

  const items = useMemo(() => holdings?.items ?? [], [holdings]);
  const sortedItems = useMemo(() => {
    const sign = sort.direction === 'asc' ? 1 : -1;
    const numeric = (value: number | null | undefined) => (typeof value === 'number' && Number.isFinite(value) ? value : Number.NEGATIVE_INFINITY);
    const metric = (item: FundHoldingItem): number => {
      if (sort.key === 'pnl') return numeric(item.pnl);
      if (sort.key === 'dayPnl') return numeric(item.dayPnl);
      if (sort.key === 'cost') return numeric(item.costTotal);
      return numeric(item.marketValue);
    };
    return [...items].sort((a, b) => (
      sort.key === 'name'
        ? sign * a.fundName.localeCompare(b.fundName, 'zh-Hant')
        : sign * (metric(a) === metric(b) ? 0 : metric(a) < metric(b) ? -1 : 1)
    ));
  }, [items, sort]);
  const heldIds = useMemo(() => new Set(items.map((h) => h.fundId)), [items]);
  const firstFundId = sortedItems[0]?.fundId;

  // 沒指定基金就選第一檔，第一次打開就有內容；只寫 state，網址維持沒有 ?fund=。
  useEffect(() => {
    if (!selectedId && firstFundId) setAutoFundId(firstFundId);
  }, [firstFundId, selectedId]);

  // 手機詳情層蓋滿畫面時鎖住底下頁面的捲動。
  useEffect(() => {
    if (!mobileLayerOpen) return undefined;
    document.body.classList.add('overflow-hidden');
    return () => document.body.classList.remove('overflow-hidden');
  }, [mobileLayerOpen]);

  useEffect(() => {
    setDetailError(null);
    if (!selectedId) {
      setDetail(null);
      setTop(null);
      return;
    }
    let cancelled = false;
    setTop(null);
    fundsApi
      .getDetail(selectedId)
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setDetail(null);
          setDetailError(getParsedApiError(err));
        }
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
  }, [detailReload, selectedId]);

  // 選中列反白並捲到看得見；桌機與手機版都在 DOM 裡，jsdom 沒有 scrollIntoView。
  useEffect(() => {
    const selected = items.find((item) => item.fundId === selectedId);
    if (!selected) return;
    const candidates = Array.from(listRef.current?.querySelectorAll<HTMLElement>('[data-row-key]') ?? [])
      .filter((element) => element.getAttribute('data-row-key') === String(selected.id));
    const target = candidates.find((element) => element.offsetParent !== null) ?? candidates[0];
    target?.scrollIntoView?.({ block: 'nearest' });
  }, [items, selectedId]);

  // 「新增持股」表單開著但還沒選基金時，選定的基金載完就帶入；已有基金的表單（含編輯中）不動
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
    setNavError(null);
    fundsApi
      .getNavHistory(detail.fundId, { period: RANGE_PERIOD[range] })
      .then((data) => {
        if (!cancelled) setPoints(data.points);
      })
      .catch((err) => {
        if (!cancelled) {
          setPoints([]);
          setNavError(getParsedApiError(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [detail, range]);

  const closeForm = () => {
    setForm(null);
    setFormErrors({});
    setFormError(null);
  };

  const openForm = (next: HoldingForm) => {
    setFormErrors({});
    setFormError(null);
    setForm(next);
  };

  const saveForm = async () => {
    if (!form || !form.fundId) return;
    const units = Number(form.units);
    const costTotal = Number(form.costTotal);
    const errors: FormErrors = {};
    if (!(units > 0)) errors.units = t('funds.form.unitsInvalid');
    if (form.costTotal.trim() === '' || !(costTotal >= 0)) errors.costTotal = t('funds.form.costInvalid');
    if (!form.asOf) errors.asOf = t('funds.form.required');
    setFormErrors(errors);
    setFormError(null);
    if (Object.keys(errors).length > 0) return;
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
      closeForm();
      await loadHoldings();
    } catch (err) {
      const parsed = getParsedApiError(err);
      // 409 是同基金同通路重複，錯誤放在通路欄。
      if (parsed.status === 409) {
        setFormErrors({ platform: parsed.message });
      } else {
        setFormError(parsed);
      }
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
      setHoldingsError(getParsedApiError(err));
    } finally {
      setPendingDelete(null);
    }
  };

  useEffect(() => {
    if (!form) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setForm(null);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [form]);

  const totalValueByCurrency = useMemo(() => {
    const map = new Map<string, number>();
    for (const total of holdings?.totals ?? []) {
      if (total.marketValue != null && total.marketValue > 0) map.set(total.currency, total.marketValue);
    }
    return map;
  }, [holdings]);

  const weightOf = (h: FundHoldingItem): number | null => {
    const total = totalValueByCurrency.get(h.currency);
    return total && h.marketValue != null ? (h.marketValue / total) * 100 : null;
  };

  const editHolding = (h: FundHoldingItem) =>
    openForm({
      id: h.id, fundId: h.fundId, fundName: h.fundName, units: String(h.units),
      costTotal: String(h.costTotal), asOf: h.asOf, platform: h.platform, note: h.note ?? '',
    });

  const rowActions = (h: FundHoldingItem) => (
    <span className="inline-flex" onClick={(event) => event.stopPropagation()}>
      <IconButton size="sm" aria-label={t('funds.holdings.edit')} icon={<Pencil className="h-4 w-4" />} onClick={() => editHolding(h)} />
      <IconButton size="sm" aria-label={t('funds.holdings.delete')} icon={<Trash2 className="h-4 w-4" />} onClick={() => setPendingDelete(h)} />
    </span>
  );

  const columns: DataTableColumn<FundHoldingItem>[] = [
    {
      key: 'name',
      header: t('funds.col.fund'),
      sortable: true,
      minWidth: 220,
      render: (h) => (
        <div className="min-w-0">
          <button type="button" className="cursor-pointer text-left font-medium" onClick={() => selectFund(h.fundId)}>{h.fundName}</button>
          <div className="text-xs text-secondary-text">
            {[h.platform, t('funds.holdings.asOf', { date: h.asOf })].filter(Boolean).join(' · ')}
          </div>
        </div>
      ),
    },
    { key: 'marketValue', header: t('funds.col.marketValue'), numeric: true, sortable: true, render: (h) => formatNumber(h.marketValue, 0) },
    {
      key: 'weight',
      header: t('funds.col.weight'),
      numeric: true,
      render: (h) => {
        const weight = weightOf(h);
        return weight === null ? NO_VALUE : `${formatNumber(weight, 1)}%`;
      },
    },
    {
      key: 'nav',
      header: t('funds.col.nav'),
      numeric: true,
      render: (h) => (
        <div>
          {formatNumber(h.nav, 2)}
          <div className={cn('whitespace-nowrap text-xs', h.isStale ? 'text-warning' : 'text-secondary-text')}>{h.navDate ?? t('funds.noNav')}</div>
        </div>
      ),
    },
    {
      key: 'dayPnl',
      header: t('funds.col.dayPnl'),
      numeric: true,
      sortable: true,
      render: (h) => (
        <div className={marketToneClass(h.dayPnl)}>
          {signedNumber(h.dayPnl)}
          <div className="text-xs">{formatPercent(h.navChangePct)}</div>
        </div>
      ),
    },
    {
      key: 'pnl',
      header: t('funds.col.pnl'),
      numeric: true,
      sortable: true,
      render: (h) => (
        <div className={marketToneClass(h.pnl)}>
          {signedNumber(h.pnl)}
          <div className="text-xs">{formatPercent(h.pnlPct)}</div>
        </div>
      ),
    },
    { key: 'cost', header: t('funds.col.cost'), numeric: true, sortable: true, render: (h) => formatNumber(h.costTotal, 0) },
    { key: 'actions', header: '', align: 'right', render: rowActions },
  ];

  const renderMobileCard = (h: FundHoldingItem) => (
    <div
      data-testid="funds-mobile-row"
      className="flex cursor-pointer items-center gap-2 px-3 py-2"
      onClick={() => {
        selectFund(h.fundId);
        setMobileDetailOpen(true);
      }}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2 text-sm">
          <span className="min-w-0 break-words font-medium">{h.fundName}</span>
          <span className="shrink-0 tabular-nums">{formatNumber(h.marketValue, 0)}</span>
        </div>
        <div className="mt-0.5 flex justify-between gap-2 text-xs tabular-nums">
          {/* 空間不夠時只截標籤，日損益數值與 % 一律完整顯示。 */}
          <span className="flex min-w-0 items-baseline">
            <span className="min-w-0 truncate text-secondary-text">{text.dayPnl}&nbsp;</span>
            <span className={cn('shrink-0 whitespace-nowrap', marketToneClass(h.dayPnl))}>{signedNumber(h.dayPnl)}（{formatPercent(h.navChangePct)}）</span>
          </span>
          <span className="shrink-0">
            <span className="text-secondary-text">{text.totalReturn} </span>
            <span className={marketToneClass(h.pnlPct)}>{formatPercent(h.pnlPct)}</span>
          </span>
        </div>
      </div>
      <ActionMenu
        size="sm"
        label={text.rowActions}
        items={[
          { key: 'edit', label: t('funds.holdings.edit'), icon: <Pencil className="h-4 w-4" />, onSelect: () => editHolding(h) },
          { key: 'delete', label: t('funds.holdings.delete'), icon: <Trash2 className="h-4 w-4" />, danger: true, onSelect: () => setPendingDelete(h) },
        ]}
      />
    </div>
  );

  const overview = holdings && items.length > 0 ? (
    <div className="space-y-2">
      {holdings.totals.map((total) => (
        <MetricGroup key={total.currency} columns={4}>
          <Metric
            label={t('funds.overview.marketValue', { currency: total.currency })}
            value={formatNumber(total.marketValue, 0)}
          />
          <Metric
            label={t('funds.overview.pnl')}
            value={<span className={marketToneClass(total.pnl)}>{signedNumber(total.pnl)}</span>}
            hint={formatPercent(total.pnlPct)}
          />
          <Metric
            label={t('funds.overview.dayPnl')}
            value={<span className={marketToneClass(total.dayPnl)}>{signedNumber(total.dayPnl)}</span>}
          />
          <Metric label={t('funds.overview.cost')} value={formatNumber(total.costTotal, 0)} />
        </MetricGroup>
      ))}
    </div>
  ) : null;

  const holdingsCard = (
    <Card variant="surface" padding="md">
      <h2 className="mb-3 text-base font-semibold">{t('funds.holdings.title')}</h2>
      {holdingsError ? (
        <div className="mb-3 space-y-2">
          <ApiErrorAlert error={holdingsError} onDismiss={() => setHoldingsError(null)} />
          <Button size="sm" variant="secondary" onClick={() => void loadHoldings()}>{t('funds.retry')}</Button>
        </div>
      ) : null}
      {holdings?.navError ? <InlineAlert className="mb-3" variant="warning" message={t('funds.holdings.navError')} /> : null}
      {!holdings ? (
        holdingsError ? null : (
          <div data-testid="funds-holdings-skeleton" className="space-y-2" aria-hidden="true">
            <SkeletonBlock className="h-10" />
            <SkeletonBlock className="h-10" />
          </div>
        )
      ) : items.length === 0 ? (
        <EmptyState title={t('funds.holdings.empty')} description={t('funds.holdings.emptyHint')} />
      ) : (
        <div ref={listRef}>
          <DataTable
            aria-label={t('funds.holdings.title')}
            density="regular"
            columns={columns}
            rows={sortedItems}
            rowKey={(h) => String(h.id)}
            sort={sort}
            onSortChange={setSort}
            onRowClick={(h) => selectFund(h.fundId)}
            // On phones the row only lights up while its detail layer is open; the auto-selection stays unmarked.
            isRowHighlighted={(h) => h.fundId === selectedId && (!narrow || mobileDetailOpen)}
            renderMobileCard={renderMobileCard}
          />
        </div>
      )}
    </Card>
  );

  const shownDetail = detail && detail.fundId === selectedId ? detail : null;
  const layerTitle = items.find((item) => item.fundId === selectedId)?.fundName ?? shownDetail?.name ?? '';
  const navValues = points.map((point) => point.nav);
  const axisDigits = navAxisDigits(navValues);
  const unitCost = shownDetail ? fundUnitCost(items, shownDetail.fundId) : null;
  const chartUp = points.length > 1 && points[points.length - 1].nav >= points[0].nav;
  const rangeChange = points.length > 1 ? (points[points.length - 1].nav / points[0].nav - 1) * 100 : null;
  // 同一檔可能在多個通路持有，合計成一行；任何一筆算不出損益就整體顯示「—」。
  const myLots = shownDetail ? items.filter((item) => item.fundId === shownDetail.fundId) : [];
  const myUnits = myLots.reduce((sum, item) => sum + item.units, 0);
  const myCost = myLots.reduce((sum, item) => sum + item.costTotal, 0);
  const myPnl = myLots.length > 0 && myLots.every((item) => item.pnl != null)
    ? myLots.reduce((sum, item) => sum + (item.pnl ?? 0), 0)
    : null;
  const myPnlPct = myPnl != null && myCost > 0 ? (myPnl / myCost) * 100 : null;

  const infoRows: [UiTextKey, React.ReactNode][] = shownDetail
    ? [
        ['funds.info.company', shownDetail.company],
        ['funds.info.type', shownDetail.typeName ?? shownDetail.typeCode],
        ['funds.info.area', shownDetail.investArea],
        ['funds.info.currency', shownDetail.currency],
        ['funds.info.inception', shownDetail.inceptionDate],
        ['funds.info.aum', shownDetail.aum != null ? `${formatNumber(shownDetail.aum / 1e8, 1)} ${t('funds.info.hundredMillion')} ${shownDetail.aumCurrency ?? ''}（${shownDetail.aumDate ?? NO_VALUE}）` : null],
        ['funds.info.dividend', shownDetail.dividendPolicy],
        ['funds.info.isin', shownDetail.isin],
        ['funds.info.fundId', shownDetail.fundId],
      ]
    : [];

  const detailBody = detailError ? (
    <div className="space-y-2">
      <ApiErrorAlert error={detailError} onDismiss={() => setDetailError(null)} />
      <Button size="sm" variant="secondary" onClick={() => setDetailReload((value) => value + 1)}>{t('funds.retry')}</Button>
    </div>
  ) : !shownDetail ? (
    <div data-testid="funds-detail-skeleton" className="space-y-3" aria-hidden="true">
      <SkeletonBlock className="h-8 w-2/3" />
      <SkeletonBlock className="h-16" />
      <SkeletonBlock className="h-60" />
    </div>
  ) : (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="break-words text-lg font-semibold">{shownDetail.name}</h2>
          <div className="text-xs text-secondary-text">{[shownDetail.company, shownDetail.typeName].filter(Boolean).join(' · ')}</div>
          {!heldIds.has(shownDetail.fundId) ? (
            <Button className="mt-2" size="sm" variant="secondary" onClick={() => openForm(emptyForm(shownDetail))}>
              <Plus className="h-4 w-4" />
              {t('funds.detail.addHolding')}
            </Button>
          ) : null}
        </div>
      </div>
      {myLots.length > 0 ? (
        <div data-testid="funds-my-holding" className="text-sm tabular-nums">
          <span className="text-secondary-text">{text.myHolding}：</span>
          {formatNumber(myUnits)} {text.units}
          <span className="text-secondary-text"> · {text.cost} </span>
          {formatNumber(myCost, 0)}
          <span className="text-secondary-text"> · {text.pnl} </span>
          <span className={marketToneClass(myPnl)}>
            {signedNumber(myPnl)}{myPnlPct != null ? `（${formatPercent(myPnlPct)}）` : ''}
          </span>
        </div>
      ) : null}
      {shownDetail.isStale ? <InlineAlert variant="warning" message={t('funds.detail.stale')} /> : null}
      {shownDetail.historyError ? <InlineAlert variant="warning" message={t('funds.detail.historyError')} /> : null}

      <section>
        <SectionTitle>{t('funds.section.nav')}</SectionTitle>
        <div className="mb-3 tabular-nums">
          <span className="text-2xl font-semibold">{formatNumber(shownDetail.nav, 2)}</span>
          <span className={cn('ml-3 text-sm', marketToneClass(shownDetail.navChangePct))}>
            {signedNumber(shownDetail.navChange, 2)} ({formatPercent(shownDetail.navChangePct)})
          </span>
          <span className={cn('ml-3 whitespace-nowrap text-xs', shownDetail.isStale ? 'text-warning' : 'text-secondary-text')}>
            {t('funds.detail.navDate', { date: shownDetail.navDate ?? NO_VALUE })}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
          {RETURN_KEYS.map((key) => (
            <div key={key} className="rounded-lg border border-border/60 p-2 text-center">
              <div className="text-xs text-secondary-text">{t(`funds.return.${key}` as UiTextKey)}</div>
              <div className={cn('text-sm font-medium tabular-nums', marketToneClass(shownDetail.returns[key]))}>{formatPercent(shownDetail.returns[key])}</div>
            </div>
          ))}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-secondary-text">
          <span>{t('funds.risk.drawdown')}：<span className="tabular-nums text-foreground">{formatPercent(shownDetail.risk.maxDrawdown)}</span></span>
          <span>{t('funds.risk.volatility')}：<span className="tabular-nums text-foreground">{shownDetail.risk.volatility == null ? NO_VALUE : `${formatNumber(shownDetail.risk.volatility, 1)}%`}</span></span>
          <span>{t('funds.returns.note')}</span>
        </div>
      </section>

      <section>
        <SectionTitle>{t('funds.section.chart')}</SectionTitle>
        {/* Equal-width single row: children grow evenly instead of keeping their intrinsic width. */}
        <Segmented
          size="sm"
          aria-label={text.rangeLabel}
          value={range}
          onChange={setRange}
          options={RANGES.map((r) => ({ value: r, label: t(`funds.range.${r}` as UiTextKey) }))}
          className="mb-2 flex w-full [&>button]:flex-1 [&>button]:px-0"
        />
        {points.length > 1 ? (
          <div data-testid="funds-range-row" className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-secondary-text">
            <span>{points[0].date} ~ {points[points.length - 1].date}</span>
            <span className={marketToneClass(rangeChange)}>{formatPercent(rangeChange)}</span>
            <span>{t('funds.chart.high')} {formatNumber(Math.max(...navValues), axisDigits)}</span>
            <span>{t('funds.chart.low')} {formatNumber(Math.min(...navValues), axisDigits)}</span>
            {unitCost !== null ? <span>{t('funds.chart.costLine', { value: formatNumber(unitCost, 2) })}</span> : null}
          </div>
        ) : null}
        {navError ? (
          <InlineAlert variant="warning" message={t('funds.chart.error')} />
        ) : points.length === 0 ? (
          <div className="py-10 text-center text-xs text-secondary-text">{t('funds.chart.empty')}</div>
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'hsl(var(--secondary-text))' }} axisLine={false} tickLine={false} height={18} minTickGap={48} />
              <YAxis domain={['auto', 'auto']} width={56} tick={{ fontSize: 11 }} tickFormatter={(v) => Number(v).toFixed(axisDigits)} />
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
              {unitCost !== null ? (
                <ReferenceLine y={unitCost} stroke="hsl(var(--secondary-text))" strokeDasharray="4 4" ifOverflow="extendDomain" />
              ) : null}
              <Line type="monotone" dataKey="nav" dot={false} strokeWidth={1.5} stroke={chartUp ? '#ef4444' : '#10b981'} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </section>

      <section>
        <SectionTitle>{t('funds.top.title')}</SectionTitle>
        {!top ? (
          <SkeletonBlock className="h-24" />
        ) : top.items.length === 0 ? (
          <div className="text-xs text-secondary-text">{t(top.error === 'not_mapped' ? 'funds.top.notMapped' : 'funds.top.unavailable')}</div>
        ) : (
          <table className="w-full text-sm tabular-nums">
            <tbody>
              {top.items.map((item, idx) => (
                <tr key={`${item.name}-${idx}`} className="border-t border-border/60">
                  <td className="py-1 pr-2">
                    {item.name ?? NO_VALUE}
                    {item.ledgerSymbol ? <Badge variant="info" className="ml-2 align-middle">{t('funds.top.held')}</Badge> : null}
                  </td>
                  <td className="py-1 pr-2 text-xs text-secondary-text">{item.sector ?? ''}</td>
                  <td className="py-1 text-right">{item.weight == null ? NO_VALUE : `${formatNumber(item.weight, 2)}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="mt-1 text-xs text-secondary-text">
          {t('funds.top.source')}
          {top?.asOfMonth ? ` · ${t('funds.top.month', { month: top.asOfMonth })}` : ''}
        </div>
      </section>

      <section>
        <SectionTitle>{t('funds.section.info')}</SectionTitle>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          {infoRows.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="text-secondary-text">{t(key)}</dt>
              <dd className="min-w-0 break-words">{value || NO_VALUE}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-3 text-xs text-secondary-text">{t('funds.detail.source', { points: String(shownDetail.historyPoints), start: shownDetail.historyStart ?? NO_VALUE })}</div>
      </section>
    </div>
  );

  const formDialog = form ? createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4 backdrop-blur-sm" role="presentation">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={form.id != null ? t('funds.holdings.edit') : t('funds.holdings.add')}
        className="max-h-full w-full max-w-lg space-y-3 overflow-y-auto rounded-[var(--radius-card)] border border-border/70 bg-card p-5"
      >
        <h2 className="text-base font-semibold">
          {form.id != null ? t('funds.holdings.edit') : t('funds.holdings.add')}
          {form.fundName ? `：${form.fundName}` : ''}
        </h2>
        {form.id == null ? (
          <FundSearchBox
            heldIds={heldIds}
            onPick={(item) => setForm((prev) => (prev ? { ...prev, fundId: item.fundId, fundName: item.name } : prev))}
          />
        ) : null}
        {!form.fundId ? <InlineAlert variant="info" message={t('funds.holdings.pickFund')} /> : null}
        {formError ? <ApiErrorAlert error={formError} onDismiss={() => setFormError(null)} /> : null}
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label={t('funds.col.units')} type="number" min="0" step="any" value={form.units} error={formErrors.units}
            onChange={(e) => setForm({ ...form, units: e.target.value })} />
          <Input label={t('funds.form.costTotal')} type="number" min="0" step="any" value={form.costTotal} error={formErrors.costTotal}
            onChange={(e) => setForm({ ...form, costTotal: e.target.value })} />
          <Input label={t('funds.form.asOf')} type="date" value={form.asOf} error={formErrors.asOf}
            onChange={(e) => setForm({ ...form, asOf: e.target.value })} />
          <Input label={t('funds.col.platform')} maxLength={64} value={form.platform} error={formErrors.platform}
            onChange={(e) => setForm({ ...form, platform: e.target.value })} />
          <div className="sm:col-span-2">
            <Input label={t('funds.form.note')} maxLength={255} value={form.note}
              onChange={(e) => setForm({ ...form, note: e.target.value })} />
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={closeForm}>{t('funds.form.cancel')}</Button>
          <Button size="sm" onClick={() => void saveForm()} disabled={saving || !form.fundId}>{t('funds.form.save')}</Button>
        </div>
      </div>
    </div>,
    document.body,
  ) : null;

  return (
    <AppPage className="space-y-5">
      <PageHeader
        title={t('funds.title')}
        actions={(
          <>
            <div data-testid="funds-header-search" className="w-full md:w-96">
              <FundSearchBox
                heldIds={heldIds}
                onPick={(item) => {
                  selectFund(item.fundId);
                  setMobileDetailOpen(true);
                }}
              />
            </div>
            <IconButton aria-label={t('funds.refresh')} icon={<RefreshCw className="h-4 w-4" />} onClick={() => void loadHoldings()} />
            {narrow ? (
              <IconButton
                aria-label={text.addFund}
                icon={<Plus className="h-4 w-4" />}
                onClick={() => openForm(emptyForm(shownDetail ?? undefined))}
              />
            ) : (
              <Button variant="secondary" onClick={() => openForm(emptyForm(shownDetail ?? undefined))}>
                <Plus className="h-4 w-4" />
                {text.addFund}
              </Button>
            )}
          </>
        )}
      />
      {overview}
      {holdingsCard}
      {mobileLayerOpen ? createPortal(
        <div
          data-testid="funds-detail"
          className="fixed inset-0 z-[45] overflow-y-auto bg-background px-4 pt-0 pb-[calc(56px+env(safe-area-inset-bottom))]"
        >
          {/* safe-area 放在 sticky 標題自己身上，背景蓋到最頂，捲動內容不會從上方縫隙露出。 */}
          <div
            data-testid="funds-detail-header"
            className="sticky top-0 z-10 -mx-4 mb-3 flex min-h-[calc(3rem+env(safe-area-inset-top))] items-center gap-2 border-b border-border/60 bg-background px-2 pt-[env(safe-area-inset-top)]"
          >
            <Button className="shrink-0" size="sm" variant="ghost" onClick={closeMobileDetail}>
              <ArrowLeft className="h-4 w-4" />
              {t('funds.detail.back')}
            </Button>
            <span className="min-w-0 flex-1 truncate text-sm font-medium">{layerTitle}</span>
          </div>
          <Card variant="surface" padding="md">{detailBody}</Card>
        </div>,
        document.body,
      ) : selectedId && !narrow ? (
        <div data-testid="funds-detail">
          <Card variant="surface" padding="md">{detailBody}</Card>
        </div>
      ) : !selectedId && holdings && items.length === 0 ? (
        <div className="hidden md:block">
          <Card variant="surface" padding="md">
            <EmptyState title={t('funds.detail.none')} description={t('funds.search.hint')} />
          </Card>
        </div>
      ) : null}
      <p className="text-xs text-secondary-text">{t('funds.description')}</p>
      {formDialog}
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
