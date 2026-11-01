import { useState } from 'react';
import type React from 'react';
import { ArrowDown, ArrowUp, Trash2 } from 'lucide-react';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { Button } from '../common';
import { StockAutocomplete } from '../StockAutocomplete';
import { parseStockListValue } from '../../utils/stockList';
import { looksLikeStockCode } from '../../utils/validation';

interface StockListEditorProps {
  /** 給搜尋框的 id，讓欄位 label 與「維護自選」的捲動定位找得到。 */
  id: string;
  value: string;
  disabled?: boolean;
  onChange: (nextValue: string) => void;
}

function moveItem(codes: string[], index: number, offset: -1 | 1): string[] {
  const target = index + offset;
  if (target < 0 || target >= codes.length) return codes;
  const next = [...codes];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

/** STOCK_LIST 專屬編輯器。儲存格式不變：一律輸出英文逗號分隔的字串，只有順序會變。 */
export const StockListEditor: React.FC<StockListEditorProps> = ({ id, value, disabled = false, onChange }) => {
  const { t } = useUiLanguage();
  const [query, setQuery] = useState('');
  const [message, setMessage] = useState('');
  const codes = parseStockListValue(value);

  const emit = (nextCodes: string[]) => {
    setMessage('');
    onChange(nextCodes.join(','));
  };

  const addCode = (rawCode: string, source?: 'manual' | 'autocomplete') => {
    const code = rawCode.trim().toUpperCase();
    if (!code) return;
    // 建議清單來的是索引裡的代號；手打才驗格式，避免把股名寫進 STOCK_LIST。
    if (source !== 'autocomplete' && !looksLikeStockCode(code)) {
      setMessage(t('settings.stockList.invalid', { code: rawCode.trim() }));
      return;
    }
    if (codes.some((existing) => existing.toUpperCase() === code)) {
      setMessage(t('settings.stockList.duplicate', { code }));
      setQuery('');
      return;
    }
    setQuery('');
    emit([...codes, code]);
  };

  return (
    <div className="space-y-3">
      <StockAutocomplete
        id={id}
        value={query}
        onChange={(next) => {
          setQuery(next);
          setMessage('');
        }}
        onSubmit={(code, _name, source) => addCode(code, source)}
        placeholder={t('settings.stockList.addPlaceholder')}
        disabled={disabled}
      />
      {message ? <p className="text-xs text-warning [overflow-wrap:anywhere]" role="status">{message}</p> : null}

      <p className="text-xs text-muted-text">{t('settings.stockList.count', { count: codes.length })}</p>

      {codes.length ? (
        <ul className="divide-y divide-[var(--settings-border-soft)] border-y border-[var(--settings-border-soft)]" data-testid="stock-list-rows">
          {codes.map((code, index) => (
            <li key={`${code}-${index}`} className="flex items-center gap-2 py-1.5">
              <span className="min-w-0 flex-1 truncate font-mono text-sm text-foreground">{code}</span>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="h-8 w-8 px-0"
                aria-label={t('settings.stockList.moveUp', { code })}
                disabled={disabled || index === 0}
                onClick={() => emit(moveItem(codes, index, -1))}
              >
                <ArrowUp className="h-4 w-4" aria-hidden="true" />
              </Button>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="h-8 w-8 px-0"
                aria-label={t('settings.stockList.moveDown', { code })}
                disabled={disabled || index === codes.length - 1}
                onClick={() => emit(moveItem(codes, index, 1))}
              >
                <ArrowDown className="h-4 w-4" aria-hidden="true" />
              </Button>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="h-8 w-8 px-0"
                aria-label={t('settings.stockList.remove', { code })}
                disabled={disabled}
                onClick={() => emit(codes.filter((_, rowIndex) => rowIndex !== index))}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-text">{t('settings.stockList.empty')}</p>
      )}

      <details>
        <summary className="cursor-pointer text-xs font-medium text-secondary-text">{t('settings.stockList.rawToggle')}</summary>
        <textarea
          aria-label={t('settings.stockList.rawToggle')}
          className="input-surface input-focus-glow mt-2 min-h-[92px] w-full resize-y rounded-xl border bg-transparent px-4 py-3 text-sm transition-all focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      </details>
    </div>
  );
};
