import type React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { portfolioApi } from '../../api/portfolio';
import { stocksApi } from '../../api/stocks';
import { StockAutocomplete } from '../StockAutocomplete';
import type {
  AlertRuleCreateRequest,
  AlertRuleItem,
  AlertSeverity,
  AlertTargetScope,
  AlertType,
  MarketLightStatus,
  MarketRegion,
  PortfolioStopLossMode,
} from '../../types/alerts';
import type { PortfolioAccountItem } from '../../types/portfolio';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { formatUiText, type UiLanguage } from '../../i18n/uiText';
import {
  ALERT_CHANGE_DIRECTION_OPTIONS,
  ALERT_CROSS_DIRECTION_OPTIONS,
  ALERT_FORM_TEXT,
  ALERT_MARKET_LIGHT_STATUS_OPTIONS,
  ALERT_MARKET_REGION_OPTIONS,
  ALERT_MARKET_TYPE_OPTIONS,
  ALERT_PAGE_TEXT,
  ALERT_PORTFOLIO_TYPE_OPTIONS,
  ALERT_PRICE_DIRECTION_OPTIONS,
  ALERT_SEVERITY_OPTIONS,
  ALERT_STOP_LOSS_MODE_OPTIONS,
  ALERT_SYMBOL_TYPE_OPTIONS,
  ALERT_TARGET_SCOPE_OPTIONS,
  ALERT_THRESHOLD_DIRECTION_OPTIONS,
} from '../../locales/featureText';
import { ALERTS_TEXT } from '../../locales/alertsText';
import { currencyUnitLabel, formatNumber, formatPercent } from '../../utils/format';
import { validateStockCode } from '../../utils/validation';
import { Button, Checkbox, Input, Select } from '../common';

const MAX_REQUESTED_DAYS = 365;
const COOLDOWN_DAILY = 86400;
const COOLDOWN_HOURLY = 3600;

// 新增、編輯、範本共用：有 id 就是編輯。
export type AlertRuleFormInitial = Partial<AlertRuleItem>;

interface AlertRuleFormProps {
  onSubmit: (payload: AlertRuleCreateRequest) => Promise<boolean | void> | boolean | void;
  isSubmitting?: boolean;
  initial?: AlertRuleFormInitial | null;
  onCancel?: () => void;
}

function initialCooldown(initial?: AlertRuleFormInitial | null): number {
  const value = (initial?.cooldownPolicy as { cooldownSeconds?: unknown } | null | undefined)?.cooldownSeconds;
  return typeof value === 'number' ? value : COOLDOWN_DAILY;
}

function textOf(value: number | undefined | null, fallback = ''): string {
  return value === undefined || value === null ? fallback : String(value);
}

// Currency prefix for the price field; only the two markets this fork trades get one.
function priceCurrency(code: string): string {
  if (/\.(TW|TWO)$/i.test(code)) return currencyUnitLabel('TWD');
  if (/^[A-Z][A-Z.-]{0,9}$/i.test(code)) return currencyUnitLabel('USD');
  return '';
}

// Quick-fill values keep two decimals at most so the number input's step accepts them.
function roundPrice(value: number): number {
  return Math.round(value * 100) / 100;
}

function isPortfolioScope(scope: AlertTargetScope): boolean {
  return scope === 'portfolio_holdings' || scope === 'portfolio_account';
}

function defaultAlertTypeForScope(scope: AlertTargetScope): AlertType {
  if (scope === 'market') return 'market_light_status';
  return scope === 'portfolio_account' ? 'portfolio_stop_loss' : 'price_cross';
}

function optionsForScope(scope: AlertTargetScope, language: UiLanguage) {
  if (scope === 'market') return ALERT_MARKET_TYPE_OPTIONS[language];
  return scope === 'portfolio_account' ? ALERT_PORTFOLIO_TYPE_OPTIONS[language] : ALERT_SYMBOL_TYPE_OPTIONS[language];
}

export const AlertRuleForm: React.FC<AlertRuleFormProps> = ({ onSubmit, isSubmitting = false, initial = null, onCancel }) => {
  const { language } = useUiLanguage();
  const text = ALERT_FORM_TEXT[language];
  const pageText = ALERT_PAGE_TEXT[language];
  const alertsText = ALERTS_TEXT[language];
  const isEdit = initial?.id != null;
  // tw_levels 的價位來自看板的 SMC 清單，改價會和訊息裡的區間對不上（docs/tw-level-alerts.md）。
  const levelLocked = initial?.source === 'tw_levels';
  const params = initial?.parameters;
  const initialScope = initial?.targetScope ?? 'single_symbol';
  const [name, setName] = useState(initial?.name ?? '');
  const [targetScope, setTargetScope] = useState<AlertTargetScope>(initialScope);
  const [target, setTarget] = useState(initialScope === 'single_symbol' ? initial?.target ?? '' : '');
  const [portfolioTarget, setPortfolioTarget] = useState(isPortfolioScope(initialScope) ? initial?.target ?? 'all' : 'all');
  const [marketRegion, setMarketRegion] = useState<MarketRegion>(initialScope === 'market' ? (initial?.target as MarketRegion) ?? 'tw' : 'tw');
  const [cooldownSeconds, setCooldownSeconds] = useState(initialCooldown(initial));
  const [fetchedQuote, setFetchedQuote] = useState<{ code: string; price: number | null; name: string | null } | null>(null);
  // Name from the autocomplete pick, keyed by code so typing a different code drops it.
  const [pickedName, setPickedName] = useState<{ code: string; name: string } | null>(null);
  const [accounts, setAccounts] = useState<PortfolioAccountItem[]>([]);
  const [accountsError, setAccountsError] = useState<string | null>(null);
  const [alertType, setAlertType] = useState<AlertType>(initial?.alertType ?? 'price_cross');
  const [severity, setSeverity] = useState<AlertSeverity>(initial?.severity ?? 'warning');
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [priceDirection, setPriceDirection] = useState<'above' | 'below'>(params?.direction === 'below' ? 'below' : 'above');
  const [changeDirection, setChangeDirection] = useState<'up' | 'down'>(params?.direction === 'down' ? 'down' : 'up');
  const [thresholdDirection, setThresholdDirection] = useState<'above' | 'below'>(params?.direction === 'below' ? 'below' : 'above');
  const [crossDirection, setCrossDirection] = useState<'bullish_cross' | 'bearish_cross'>(params?.direction === 'bearish_cross' ? 'bearish_cross' : 'bullish_cross');
  const [stopLossMode, setStopLossMode] = useState<PortfolioStopLossMode>(params?.mode ?? 'near');
  const [price, setPrice] = useState(textOf(params?.price));
  const [changePct, setChangePct] = useState(textOf(params?.changePct));
  const [multiplier, setMultiplier] = useState(textOf(params?.multiplier));
  const [window, setWindow] = useState(textOf(params?.window, '20'));
  const [period, setPeriod] = useState(textOf(params?.period, '12'));
  const [threshold, setThreshold] = useState(textOf(params?.threshold));
  const [fastPeriod, setFastPeriod] = useState(textOf(params?.fastPeriod, '12'));
  const [slowPeriod, setSlowPeriod] = useState(textOf(params?.slowPeriod, '26'));
  const [signalPeriod, setSignalPeriod] = useState(textOf(params?.signalPeriod, '9'));
  const [kPeriod, setKPeriod] = useState(textOf(params?.kPeriod, '3'));
  const [dPeriod, setDPeriod] = useState(textOf(params?.dPeriod, '3'));
  const [marketLightStatuses, setMarketLightStatuses] = useState<MarketLightStatus[]>(params?.statuses ?? ['red', 'yellow']);
  const [minDrop, setMinDrop] = useState(textOf(params?.minDrop, '10'));
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!isPortfolioScope(targetScope)) return undefined;
    let cancelled = false;
    void portfolioApi.getAccounts(false)
      .then((response) => {
        if (cancelled) return;
        setAccounts(response.accounts ?? []);
        setAccountsError(null);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setAccounts([]);
        setAccountsError(error instanceof Error ? error.message : text.accountLoadFailed);
      });
    return () => {
      cancelled = true;
    };
  }, [targetScope, text.accountLoadFailed]);

  // 現價只在單檔價格規則顯示；抓不到時不顯示距離，不影響送出。
  const quoteTarget = targetScope === 'single_symbol' && alertType === 'price_cross' ? validateStockCode(target) : null;
  const quoteCode = quoteTarget?.valid ? quoteTarget.normalized : '';
  useEffect(() => {
    if (!quoteCode) return undefined;
    let cancelled = false;
    void stocksApi.getQuotes([quoteCode])
      .then((items) => {
        if (!cancelled) {
          const quote = items?.[0]?.quote;
          setFetchedQuote({ code: quoteCode, price: quote?.currentPrice ?? null, name: quote?.stockName ?? null });
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [quoteCode]);
  const currentPrice = fetchedQuote?.code === quoteCode ? fetchedQuote.price : null;
  const targetCode = targetScope === 'single_symbol' ? validateStockCode(target).normalized : '';
  const targetName = (pickedName && pickedName.code.toUpperCase() === targetCode ? pickedName.name : null)
    ?? (quoteCode && fetchedQuote?.code === quoteCode ? fetchedQuote.name : null);
  const currency = targetScope === 'single_symbol' ? priceCurrency(targetCode) : '';
  const priceChips = currentPrice != null && currentPrice > 0 && !levelLocked
    ? [
      { key: 'current', label: alertsText.chipCurrent, value: roundPrice(currentPrice) },
      { key: 'up', label: formatUiText(alertsText.chipUp, { price: formatNumber(roundPrice(currentPrice * 1.05)) }), value: roundPrice(currentPrice * 1.05) },
      { key: 'down', label: formatUiText(alertsText.chipDown, { price: formatNumber(roundPrice(currentPrice * 0.95)) }), value: roundPrice(currentPrice * 0.95) },
    ]
    : [];
  const priceTarget = Number(price);
  // 還沒填價位也先給現價，填價位時才有依據。
  const hasPriceTarget = price !== '' && Number.isFinite(priceTarget) && priceTarget > 0;
  let priceHint: string | null = null;
  if (currentPrice != null && currentPrice > 0) {
    priceHint = hasPriceTarget
      ? formatUiText(pageText.currentPrice, {
        price: formatNumber(currentPrice),
        pct: formatPercent((priceTarget / currentPrice - 1) * 100, 1),
      })
      : formatUiText(pageText.current, { price: formatNumber(currentPrice) });
  }

  const alertTypeOptions = useMemo(() => optionsForScope(targetScope, language), [language, targetScope]);
  const portfolioTargetOptions = useMemo(() => [
    { value: 'all', label: text.allAccounts },
    ...accounts.map((account) => ({
      value: String(account.id),
      label: `${account.name} #${account.id}`,
    })),
  ], [accounts, text.allAccounts]);

  const resetParameters = (nextType: AlertType) => {
    if (nextType === 'price_cross') {
      setPriceDirection('above');
      setPrice('');
    } else if (nextType === 'price_change_percent') {
      setChangeDirection('up');
      setChangePct('');
    } else if (nextType === 'volume_spike') {
      setMultiplier('');
    } else if (nextType === 'ma_price_cross') {
      setThresholdDirection('above');
      setWindow('20');
    } else if (nextType === 'rsi_threshold') {
      setThresholdDirection('above');
      setPeriod('12');
      setThreshold('');
    } else if (nextType === 'macd_cross') {
      setCrossDirection('bullish_cross');
      setFastPeriod('12');
      setSlowPeriod('26');
      setSignalPeriod('9');
    } else if (nextType === 'kdj_cross') {
      setCrossDirection('bullish_cross');
      setPeriod('9');
      setKPeriod('3');
      setDPeriod('3');
    } else if (nextType === 'cci_threshold') {
      setThresholdDirection('above');
      setPeriod('14');
      setThreshold('');
    } else if (nextType === 'portfolio_stop_loss') {
      setStopLossMode('near');
    } else if (nextType === 'market_light_status') {
      setMarketLightStatuses(['red', 'yellow']);
    } else if (nextType === 'market_light_score_drop') {
      setMinDrop('10');
    }
  };

  const toggleMarketLightStatus = (status: MarketLightStatus) => {
    setMarketLightStatuses((current) => (
      current.includes(status)
        ? current.filter((item) => item !== status)
        : [...current, status]
    ));
  };

  const parsePositiveNumber = (value: string, label: string): number | null => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setFormError(formatUiText(text.positiveNumber, { label }));
      return null;
    }
    return parsed;
  };

  const parseIntegerInRange = (value: string, label: string, min = 2, max = 250): number | null => {
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
      setFormError(formatUiText(text.integerRange, { label, min, max }));
      return null;
    }
    return parsed;
  };

  const parseFiniteNumber = (value: string, label: string): number | null => {
    if (value.trim() === '') {
      setFormError(formatUiText(text.required, { label }));
      return null;
    }
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) {
      setFormError(formatUiText(text.finiteNumber, { label }));
      return null;
    }
    return parsed;
  };

  const parseRsiThreshold = (value: string): number | null => {
    const parsed = parseFiniteNumber(value, text.rsiThreshold);
    if (parsed == null) return null;
    if (parsed < 0 || parsed > 100) {
      setFormError(text.rsiRange);
      return null;
    }
    return parsed;
  };

  const ensureRequiredBarsWithinLimit = (label: string, requiredBars: number): boolean => {
    if (requiredBars > MAX_REQUESTED_DAYS) {
      setFormError(formatUiText(text.requiredBarsLimit, { label, requiredBars, max: MAX_REQUESTED_DAYS }));
      return false;
    }
    return true;
  };

  const buildParameters = (): AlertRuleCreateRequest['parameters'] | null => {
    if (alertType === 'price_cross') {
      const parsedPrice = parsePositiveNumber(price, text.priceThreshold);
      if (parsedPrice == null) return null;
      return { direction: priceDirection, price: parsedPrice };
    }
    if (alertType === 'price_change_percent') {
      const parsedChangePct = parsePositiveNumber(changePct, text.changePctThreshold);
      if (parsedChangePct == null) return null;
      return { direction: changeDirection, changePct: parsedChangePct };
    }
    if (alertType === 'volume_spike') {
      const parsedMultiplier = parsePositiveNumber(multiplier, text.volumeMultiplier);
      if (parsedMultiplier == null) return null;
      return { multiplier: parsedMultiplier };
    }
    if (alertType === 'ma_price_cross') {
      const parsedWindow = parseIntegerInRange(window, text.maWindow);
      if (parsedWindow == null) return null;
      return { direction: thresholdDirection, window: parsedWindow };
    }
    if (alertType === 'rsi_threshold') {
      const parsedPeriod = parseIntegerInRange(period, text.rsiPeriod);
      const parsedThreshold = parseRsiThreshold(threshold);
      if (parsedPeriod == null || parsedThreshold == null) return null;
      return { direction: thresholdDirection, period: parsedPeriod, threshold: parsedThreshold };
    }
    if (alertType === 'macd_cross') {
      const parsedFast = parseIntegerInRange(fastPeriod, text.fastPeriod);
      const parsedSlow = parseIntegerInRange(slowPeriod, text.slowPeriod);
      const parsedSignal = parseIntegerInRange(signalPeriod, text.signalPeriod);
      if (parsedFast == null || parsedSlow == null || parsedSignal == null) return null;
      if (parsedFast >= parsedSlow) {
        setFormError(text.fastLessThanSlow);
        return null;
      }
      if (!ensureRequiredBarsWithinLimit('MACD', parsedSlow + parsedSignal + 1)) return null;
      return {
        direction: crossDirection,
        fastPeriod: parsedFast,
        slowPeriod: parsedSlow,
        signalPeriod: parsedSignal,
      };
    }
    if (alertType === 'kdj_cross') {
      const parsedPeriod = parseIntegerInRange(period, text.kdjPeriod);
      const parsedK = parseIntegerInRange(kPeriod, text.kPeriod);
      const parsedD = parseIntegerInRange(dPeriod, text.dPeriod);
      if (parsedPeriod == null || parsedK == null || parsedD == null) return null;
      if (!ensureRequiredBarsWithinLimit('KDJ', parsedPeriod + parsedK + parsedD + 1)) return null;
      return { direction: crossDirection, period: parsedPeriod, kPeriod: parsedK, dPeriod: parsedD };
    }
    if (alertType === 'cci_threshold') {
      const parsedPeriod = parseIntegerInRange(period, text.cciPeriod);
      const parsedThreshold = parseFiniteNumber(threshold, text.cciThreshold);
      if (parsedPeriod == null || parsedThreshold == null) return null;
      return { direction: thresholdDirection, period: parsedPeriod, threshold: parsedThreshold };
    }
    if (alertType === 'portfolio_stop_loss') {
      return { mode: stopLossMode };
    }
    if (alertType === 'market_light_status') {
      if (marketLightStatuses.length === 0) {
        setFormError(text.noMarketStatus);
        return null;
      }
      return { statuses: marketLightStatuses };
    }
    if (alertType === 'market_light_score_drop') {
      const parsedMinDrop = parsePositiveNumber(minDrop, text.scoreDropThreshold);
      if (parsedMinDrop == null) return null;
      return { minDrop: parsedMinDrop };
    }
    return {};
  };

  const handleScopeChange = (value: string) => {
    const nextScope = value as AlertTargetScope;
    const nextType = defaultAlertTypeForScope(nextScope);
    setTargetScope(nextScope);
    setAlertType(nextType);
    setPortfolioTarget('all');
    setMarketRegion('tw');
    resetParameters(nextType);
    setFormError(null);
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    let resolvedTarget = target.trim();
    if (targetScope === 'single_symbol') {
      const targetValidation = validateStockCode(target);
      if (!targetValidation.valid) {
        // validateStockCode 的訊息是寫死的簡體，只有簡體介面能用。
        setFormError(language === 'zh' ? (targetValidation.message ?? text.invalidStockCode) : text.invalidStockCode);
        return;
      }
      resolvedTarget = targetValidation.normalized;
    } else if (targetScope === 'watchlist') {
      resolvedTarget = 'default';
    } else if (targetScope === 'market') {
      resolvedTarget = marketRegion;
    } else {
      resolvedTarget = portfolioTarget;
    }

    const parameters = buildParameters();
    if (parameters == null) return;

    setFormError(null);
    const submitted = await onSubmit({
      name: name.trim() || undefined,
      targetScope,
      target: resolvedTarget,
      alertType,
      parameters,
      severity,
      enabled,
      ...((isEdit || cooldownSeconds !== COOLDOWN_DAILY) ? { cooldownSeconds } : {}),
    });
    if (submitted === false) return;
    setName('');
    setTarget('');
    setPortfolioTarget('all');
    setMarketRegion('tw');
    setPrice('');
    setChangePct('');
    setMultiplier('');
    setWindow('20');
    setPeriod('12');
    setThreshold('');
    setFastPeriod('12');
    setSlowPeriod('26');
    setSignalPeriod('9');
    setKPeriod('3');
    setDPeriod('3');
    setMarketLightStatuses(['red', 'yellow']);
    setMinDrop('10');
    resetParameters(alertType);
    setEnabled(true);
  };

  const renderTargetControl = () => {
    if (targetScope === 'single_symbol') {
      return (
        <div className="space-y-2">
          <div className="text-sm font-medium text-foreground">{text.targetCode}</div>
          <StockAutocomplete
            value={target}
            onChange={setTarget}
            onSubmit={(code, stockName) => {
              setTarget(code);
              if (stockName) setPickedName({ code, name: stockName });
            }}
            onPick={(code, stockName) => {
              setTarget(code);
              if (stockName) setPickedName({ code, name: stockName });
            }}
            ariaLabel={text.targetCode}
            placeholder={pageText.stockPlaceholder}
            disabled={isSubmitting || levelLocked}
            className="h-9 rounded-[var(--radius-control)] px-3"
          />
          {targetName ? (
            <p className="text-xs text-secondary-text" data-testid="alert-form-stock-name">
              {formatUiText(alertsText.pickedName, { name: targetName })}
            </p>
          ) : null}
        </div>
      );
    }
    if (targetScope === 'watchlist') {
      return (
        <Input
          label={text.target}
          value={pageText.watchlist}
          onChange={() => undefined}
          disabled
        />
      );
    }
    if (targetScope === 'market') {
      return (
        <Select
          label={text.marketRegion}
          value={marketRegion}
          options={ALERT_MARKET_REGION_OPTIONS[language]}
          disabled={isSubmitting}
          onChange={(value) => setMarketRegion(value as MarketRegion)}
        />
      );
    }
    return (
      <div className="space-y-2">
        <Select
          label={text.account}
          value={portfolioTarget}
          options={portfolioTargetOptions}
          disabled={isSubmitting}
          onChange={setPortfolioTarget}
        />
        {accountsError ? <p role="alert" className="text-xs text-warning">{accountsError}</p> : null}
      </div>
    );
  };

  return (
    <form className="space-y-6" noValidate onSubmit={(event) => void handleSubmit(event)}>
      <fieldset className="space-y-4">
        <legend className="mb-3 text-sm font-semibold text-foreground">{`1. ${pageText.stepWho}`}</legend>
        <div className="grid gap-4 md:grid-cols-2">
          <Select
            label={text.targetScope}
            value={targetScope}
            options={ALERT_TARGET_SCOPE_OPTIONS[language]}
            disabled={isSubmitting || levelLocked}
            onChange={handleScopeChange}
          />
          {renderTargetControl()}
        </div>
      </fieldset>

      <fieldset className="space-y-4">
        <legend className="mb-3 text-sm font-semibold text-foreground">{`2. ${pageText.stepWhen}`}</legend>
        {levelLocked ? <p className="text-xs text-warning">{pageText.levelLocked}</p> : null}
        <Select
          label={text.ruleType}
          value={alertType}
          options={alertTypeOptions}
          disabled={isSubmitting || levelLocked}
          onChange={(value) => {
            const nextType = value as AlertType;
            setAlertType(nextType);
            resetParameters(nextType);
          }}
        />

        {alertType === 'price_cross' ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Select
              label={text.direction}
              value={priceDirection}
              options={ALERT_PRICE_DIRECTION_OPTIONS[language]}
              disabled={isSubmitting || levelLocked}
              onChange={(value) => setPriceDirection(value as 'above' | 'below')}
            />
            <div className="space-y-2">
              <Input
                label={text.priceThreshold}
                type="number"
                min="0"
                step="0.0001"
                value={price}
                placeholder={alertsText.pricePlaceholder}
                hint={priceHint ?? undefined}
                trailingAction={currency ? <span className="pr-1 text-xs text-secondary-text">{currency}</span> : undefined}
                onChange={(event) => setPrice(event.target.value)}
                disabled={isSubmitting || levelLocked}
              />
              {priceChips.length ? (
                <div role="group" aria-label={alertsText.chipGroup} className="flex flex-wrap gap-1.5">
                  {priceChips.map((chip) => (
                    <button
                      key={chip.key}
                      type="button"
                      className="inline-flex h-7 items-center rounded-full border border-border/60 px-2.5 text-xs tabular-nums text-secondary-text transition-colors hover:border-primary hover:text-foreground disabled:opacity-50"
                      disabled={isSubmitting}
                      onClick={() => setPrice(String(chip.value))}
                    >
                      {chip.label}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {alertType === 'price_change_percent' ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Select
              label={text.direction}
              value={changeDirection}
              options={ALERT_CHANGE_DIRECTION_OPTIONS[language]}
              disabled={isSubmitting}
              onChange={(value) => setChangeDirection(value as 'up' | 'down')}
            />
            <Input
              label={text.changePctThreshold}
              type="number"
              min="0"
              step="0.01"
              value={changePct}
              onChange={(event) => setChangePct(event.target.value)}
              disabled={isSubmitting}
            />
          </div>
        ) : null}

        {alertType === 'volume_spike' ? (
          <Input
            label={text.volumeMultiplier}
            type="number"
            min="0"
            step="0.01"
            value={multiplier}
            onChange={(event) => setMultiplier(event.target.value)}
            disabled={isSubmitting}
          />
        ) : null}

        {alertType === 'ma_price_cross' ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Select
              label={text.maDirection}
              value={thresholdDirection}
              options={ALERT_THRESHOLD_DIRECTION_OPTIONS[language]}
              disabled={isSubmitting}
              onChange={(value) => setThresholdDirection(value as 'above' | 'below')}
            />
            <Input
              label={text.maWindow}
              type="number"
              min="2"
              max="250"
              step="1"
              value={window}
              onChange={(event) => setWindow(event.target.value)}
              disabled={isSubmitting}
            />
          </div>
        ) : null}

        {alertType === 'rsi_threshold' ? (
          <div className="grid gap-4 md:grid-cols-3">
            <Select
              label={text.thresholdDirection}
              value={thresholdDirection}
              options={ALERT_THRESHOLD_DIRECTION_OPTIONS[language]}
              disabled={isSubmitting}
              onChange={(value) => setThresholdDirection(value as 'above' | 'below')}
            />
            <Input
              label={text.rsiPeriod}
              type="number"
              min="2"
              max="250"
              step="1"
              value={period}
              onChange={(event) => setPeriod(event.target.value)}
              disabled={isSubmitting}
            />
            <Input
              label={text.rsiThreshold}
              type="number"
              min="0"
              max="100"
              step="0.01"
              value={threshold}
              onChange={(event) => setThreshold(event.target.value)}
              disabled={isSubmitting}
            />
          </div>
        ) : null}

        {alertType === 'macd_cross' ? (
          <div className="grid gap-4 md:grid-cols-4">
            <Select
              label={text.crossDirection}
              value={crossDirection}
              options={ALERT_CROSS_DIRECTION_OPTIONS[language]}
              disabled={isSubmitting}
              onChange={(value) => setCrossDirection(value as 'bullish_cross' | 'bearish_cross')}
            />
            <Input
              label={text.fastPeriod}
              type="number"
              min="2"
              max="250"
              step="1"
              value={fastPeriod}
              onChange={(event) => setFastPeriod(event.target.value)}
              disabled={isSubmitting}
            />
            <Input
              label={text.slowPeriod}
              type="number"
              min="2"
              max="250"
              step="1"
              value={slowPeriod}
              onChange={(event) => setSlowPeriod(event.target.value)}
              disabled={isSubmitting}
            />
            <Input
              label={text.signalPeriod}
              type="number"
              min="2"
              max="250"
              step="1"
              value={signalPeriod}
              onChange={(event) => setSignalPeriod(event.target.value)}
              disabled={isSubmitting}
            />
          </div>
        ) : null}

        {alertType === 'kdj_cross' ? (
          <div className="grid gap-4 md:grid-cols-4">
            <Select
              label={text.crossDirection}
              value={crossDirection}
              options={ALERT_CROSS_DIRECTION_OPTIONS[language]}
              disabled={isSubmitting}
              onChange={(value) => setCrossDirection(value as 'bullish_cross' | 'bearish_cross')}
            />
            <Input
              label={text.kdjPeriod}
              type="number"
              min="2"
              max="250"
              step="1"
              value={period}
              onChange={(event) => setPeriod(event.target.value)}
              disabled={isSubmitting}
            />
            <Input
              label={text.kPeriod}
              type="number"
              min="2"
              max="250"
              step="1"
              value={kPeriod}
              onChange={(event) => setKPeriod(event.target.value)}
              disabled={isSubmitting}
            />
            <Input
              label={text.dPeriod}
              type="number"
              min="2"
              max="250"
              step="1"
              value={dPeriod}
              onChange={(event) => setDPeriod(event.target.value)}
              disabled={isSubmitting}
            />
          </div>
        ) : null}

        {alertType === 'cci_threshold' ? (
          <div className="grid gap-4 md:grid-cols-3">
            <Select
              label={text.thresholdDirection}
              value={thresholdDirection}
              options={ALERT_THRESHOLD_DIRECTION_OPTIONS[language]}
              disabled={isSubmitting}
              onChange={(value) => setThresholdDirection(value as 'above' | 'below')}
            />
            <Input
              label={text.cciPeriod}
              type="number"
              min="2"
              max="250"
              step="1"
              value={period}
              onChange={(event) => setPeriod(event.target.value)}
              disabled={isSubmitting}
            />
            <Input
              label={text.cciThreshold}
              type="number"
              step="0.01"
              value={threshold}
              onChange={(event) => setThreshold(event.target.value)}
              disabled={isSubmitting}
            />
          </div>
        ) : null}

        {alertType === 'portfolio_stop_loss' ? (
          <Select
            label={text.stopLossMode}
            value={stopLossMode}
            options={ALERT_STOP_LOSS_MODE_OPTIONS[language]}
            disabled={isSubmitting}
            onChange={(value) => setStopLossMode(value as PortfolioStopLossMode)}
          />
        ) : null}

        {alertType === 'market_light_status' ? (
          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground">{text.triggerStatus}</div>
            <div className="grid gap-3 sm:grid-cols-2">
              {ALERT_MARKET_LIGHT_STATUS_OPTIONS[language].map((option) => (
                <Checkbox
                  key={option.value}
                  label={option.label}
                  checked={marketLightStatuses.includes(option.value)}
                  disabled={isSubmitting}
                  onChange={() => toggleMarketLightStatus(option.value)}
                />
              ))}
            </div>
          </div>
        ) : null}

        {alertType === 'market_light_score_drop' ? (
          <Input
            label={text.scoreDropThreshold}
            type="number"
            min="0"
            max="100"
            step="1"
            value={minDrop}
            onChange={(event) => setMinDrop(event.target.value)}
            disabled={isSubmitting}
          />
        ) : null}

      </fieldset>

      <fieldset className="space-y-4">
        <legend className="mb-3 text-sm font-semibold text-foreground">{`3. ${pageText.stepHow}`}</legend>
        <div className="grid gap-4 md:grid-cols-2">
          <Select
            label={pageText.frequency}
            value={String(cooldownSeconds)}
            options={[
              { value: String(COOLDOWN_DAILY), label: pageText.daily },
              { value: String(COOLDOWN_HOURLY), label: pageText.hourly },
              ...(cooldownSeconds !== COOLDOWN_DAILY && cooldownSeconds !== COOLDOWN_HOURLY
                ? [{ value: String(cooldownSeconds), label: formatUiText(pageText.everyCustom, { minutes: Math.round(cooldownSeconds / 60) }) }]
                : []),
            ]}
            disabled={isSubmitting}
            onChange={(value) => setCooldownSeconds(Number(value))}
          />
          <Select
            label={text.severity}
            value={severity}
            options={ALERT_SEVERITY_OPTIONS[language]}
            disabled={isSubmitting}
            onChange={(value) => setSeverity(value as AlertSeverity)}
          />
          <Input
            label={text.ruleName}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={text.ruleNamePlaceholder}
            disabled={isSubmitting}
          />
        </div>
        {isEdit ? null : (
          <Checkbox
            label={text.enableAfterCreate}
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
            disabled={isSubmitting}
          />
        )}
      </fieldset>

      {formError ? <p role="alert" className="text-sm text-danger">{formError}</p> : null}
      <div className="flex justify-end gap-2">
        {onCancel ? (
          <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
            {pageText.cancel}
          </Button>
        ) : null}
        <Button type="submit" isLoading={isSubmitting} loadingText={text.creating}>
          {isEdit ? pageText.save : text.create}
        </Button>
      </div>
    </form>
  );
};
