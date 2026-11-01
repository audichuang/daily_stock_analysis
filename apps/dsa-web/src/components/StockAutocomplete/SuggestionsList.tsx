/**
 * Stock search suggestion list.
 */

import type { CSSProperties } from 'react';
import type { StockSuggestion } from '../../types/stockIndex';
import { Badge } from '../common';
import { cn } from '../../utils/cn';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';

// Taiwan and US listings first (this fork's markets); the rest keep their relevance order.
const PRIORITY_MARKETS = ['TW', 'US'];
const marketRank = (market: string): number => {
  const index = PRIORITY_MARKETS.indexOf(market);
  return index === -1 ? PRIORITY_MARKETS.length : index;
};

export interface SuggestionsListProps {
  /** Suggestion list */
  suggestions: StockSuggestion[];
  /** Highlighted index */
  highlightedIndex: number;
  /** Selection callback */
  onSelect: (suggestion: StockSuggestion) => void;
  /** Mouse hover callback */
  onMouseEnter: (index: number) => void;
  /** Custom style (for Portal fixed positioning) */
  style?: CSSProperties;
}

export function SuggestionsList({
  suggestions,
  highlightedIndex,
  onSelect,
  onMouseEnter,
  style,
}: SuggestionsListProps) {
  if (suggestions.length === 0) {
    return null;
  }

  // Reorder for display only. The parent's highlightedIndex, hover and Enter all index the
  // original array, so every rendered row keeps its original index.
  const ordered = suggestions
    .map((suggestion, index) => ({ suggestion, index }))
    .sort((a, b) => marketRank(a.suggestion.market) - marketRank(b.suggestion.market) || a.index - b.index);

  return (
    <ul
      id="suggestions-list"
      className="z-[100] border-x border-b rounded-b-lg rounded-t-none max-h-60 overflow-auto"
      style={{
        ...style,
        backgroundColor: 'hsl(var(--card))',
        borderColor: 'var(--border-accent)',
        boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.3), -4px 0 15px -3px rgba(0, 0, 0, 0.2), 4px 0 15px -3px rgba(0, 0, 0, 0.2)',
      }}
      role="listbox"
    >
      {ordered.map(({ suggestion, index }) => (
        <li
          key={suggestion.canonicalCode}
          role="option"
          aria-selected={index === highlightedIndex}
          className={cn(
            'px-4 py-1 cursor-pointer flex items-center justify-between',
            'hover:bg-[var(--autocomplete-hover-bg)]/25',
            index === highlightedIndex && 'bg-[var(--autocomplete-hover-bg)]/25',
          )}
          onClick={() => onSelect(suggestion)}
          onMouseEnter={() => onMouseEnter(index)}
        >
          <div className="flex items-center gap-3">
            <MarketBadge market={suggestion.market} />

            <div className="flex flex-col">
              <span className="text-sm font-medium text-primary-text">
                {suggestion.nameZh}
              </span>
              <span className="text-sm text-secondary-text">
                {suggestion.displayCode}
              </span>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

const MARKET_BADGE_CONFIG = {
  CN: { labelKey: 'autocomplete.market.CN', className: 'border-danger/25 bg-danger/10 text-danger' },
  HK: { labelKey: 'autocomplete.market.HK', className: 'border-success/25 bg-success/10 text-success' },
  US: { labelKey: 'autocomplete.market.US', className: 'border-cyan/25 bg-cyan/10 text-cyan' },
  JP: { labelKey: 'autocomplete.market.JP', className: 'border-indigo-500/25 bg-indigo-500/10 text-indigo-500' },
  KR: { labelKey: 'autocomplete.market.KR', className: 'border-rose-500/25 bg-rose-500/10 text-rose-500' },
  TW: { labelKey: 'autocomplete.market.TW', className: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-600' },
  INDEX: { labelKey: 'autocomplete.market.INDEX', className: 'border-purple/25 bg-purple/10 text-purple' },
  ETF: { labelKey: 'autocomplete.market.ETF', className: 'border-warning/25 bg-warning/10 text-warning' },
  BSE: { labelKey: 'autocomplete.market.BSE', className: 'border-orange-500/25 bg-orange-500/10 text-orange-500' },
} as const satisfies Record<string, { labelKey: UiTextKey; className: string }>;

function MarketBadge({ market }: { market: string }) {
  const { t } = useUiLanguage();
  const config = MARKET_BADGE_CONFIG[market as keyof typeof MARKET_BADGE_CONFIG];

  if (!config) {
    throw new Error(`Unsupported market in stock suggestion: ${market}`);
  }

  return (
    <Badge variant="default" size="sm" className={cn('min-w-[3rem] justify-center shadow-none', config.className)}>
      {t(config.labelKey)}
    </Badge>
  );
}

export default SuggestionsList;
