import type React from 'react';
import { useState, useCallback, useRef, useEffect, useId } from 'react';
import { Check, Pencil } from 'lucide-react';
import { Badge, Button, ConfirmDialog, InlineAlert, ScrollArea } from '../common';
import { DashboardPanelHeader, DashboardStateBlock } from '../dashboard';
import { StockBarItemComponent } from './StockBarItem';
import type { StockQuote } from '../../api/stocks';
import type { StockBarItem as StockBarItemType } from '../../types/analysis';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { stockQuoteKey } from '../../hooks/useStockQuotes';
import { HOME_TEXT, formatHomeText } from '../../locales/homeText';

interface StockBarProps {
  items: StockBarItemType[];
  isLoading: boolean;
  selectedStockCode?: string;
  selectedRecordId?: number;
  onItemClick: (recordId: number) => void;
  /** 失敗要 throw，才會顯示失敗提示。 */
  onDeleteStock?: (stockCode: string) => Promise<void> | void;
  isDeleting?: boolean;
  className?: string;
  quotes?: Map<string, StockQuote>;
  marketLightLabel?: string;
  /** 市場篩選與排序列，由外層提供。 */
  controls?: React.ReactNode;
  /**
   * card（預設）：自帶 glass-card 外框與標題；list：無框，嵌在外層卡片裡，
   * 表頭（筆數、編輯、篩選）固定不捲動，只有清單捲動。
   */
  variant?: 'card' | 'list';
  /** 大盤複盤列標題裡的市場，例如「美股」。 */
  marketReviewRegionLabel?: string;
}

/**
 * 个股栏组件：以股票维度展示历史分析记录，每只股票只显示一条。
 * 大盤複盤固定在最上面；核取框只在編輯模式出現，刪除要確認。
 */
export const StockBar: React.FC<StockBarProps> = ({
  items,
  isLoading,
  selectedStockCode,
  selectedRecordId,
  onItemClick,
  onDeleteStock,
  isDeleting = false,
  className = '',
  quotes,
  marketLightLabel,
  controls,
  variant = 'card',
  marketReviewRegionLabel,
}) => {
  const { t, language } = useUiLanguage();
  const isList = variant === 'list';
  const isMarketReview = (code: string) => code === 'MARKET';
  const [editMode, setEditMode] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleteFailed, setDeleteFailed] = useState(false);
  const [selectedCodes, setSelectedCodes] = useState<Set<string>>(new Set());
  const selectAllRef = useRef<HTMLInputElement>(null);
  const selectAllId = useId();

  const pinnedItems = items.filter((item) => isMarketReview(item.stockCode));
  const orderedItems = [...pinnedItems, ...items.filter((item) => !isMarketReview(item.stockCode))];
  const selectedCount = [...selectedCodes].filter((code) => items.some((item) => item.stockCode === code)).length;
  const allVisibleSelected = items.length > 0 && selectedCount === items.length;
  const someVisibleSelected = selectedCount > 0 && !allVisibleSelected;

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someVisibleSelected;
    }
  }, [someVisibleSelected]);

  const toggleCode = useCallback((code: string) => {
    setSelectedCodes((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }, []);

  const toggleSelectAll = () => {
    setSelectedCodes(allVisibleSelected ? new Set() : new Set(items.map((item) => item.stockCode)));
  };

  const handleDeleteSelected = async () => {
    setConfirmOpen(false);
    if (!onDeleteStock || selectedCodes.size === 0) return;
    setDeleteFailed(false);
    const remaining = new Set(selectedCodes);
    try {
      for (const code of selectedCodes) {
        await onDeleteStock(code);
        remaining.delete(code);
      }
    } catch {
      setDeleteFailed(true);
    }
    // 成功的取消勾選，失敗的留著讓使用者重試。
    setSelectedCodes(remaining);
  };

  const toggleEditMode = () => {
    setEditMode((current) => !current);
    setSelectedCodes(new Set());
    setDeleteFailed(false);
  };

  const countNode = editMode && selectedCount > 0 ? (
    <Badge variant="info" size="sm">{t('common.selectedCount', { count: selectedCount })}</Badge>
  ) : items.length > 0 ? (
    <span className="text-[11px] text-muted-text">
      {isList
        ? formatHomeText(HOME_TEXT[language].historySubline, { count: items.length })
        : t('common.itemsCount', { count: items.length })}
    </span>
  ) : null;

  const editToggle = items.length > 0 && onDeleteStock ? (
    isList ? (
      <Button
        variant="ghost"
        size="sm"
        className="h-7 w-7 shrink-0 px-0"
        aria-pressed={editMode}
        aria-label={editMode ? t('watchlist.editDone') : t('watchlist.edit')}
        onClick={toggleEditMode}
      >
        {editMode
          ? <Check className="h-3.5 w-3.5" aria-hidden="true" />
          : <Pencil className="h-3.5 w-3.5" aria-hidden="true" />}
      </Button>
    ) : (
      <Button
        variant="ghost"
        size="sm"
        aria-pressed={editMode}
        onClick={toggleEditMode}
      >
        {editMode ? t('watchlist.editDone') : t('watchlist.edit')}
      </Button>
    )
  ) : null;

  const editBar = (
    <>
      {editMode && items.length > 0 && onDeleteStock ? (
        <div className="flex items-center gap-2">
          <label
            className="flex flex-1 cursor-pointer items-center gap-2 rounded-lg px-2 py-1"
            htmlFor={selectAllId}
          >
            <input
              id={selectAllId}
              ref={selectAllRef}
              type="checkbox"
              checked={allVisibleSelected}
              onChange={toggleSelectAll}
              disabled={isDeleting}
              aria-label={t('history.selectAllStockAria')}
              className="h-3.5 w-3.5 cursor-pointer bg-transparent accent-primary focus:ring-primary/30 disabled:opacity-50"
            />
            <span className="text-[11px] text-muted-text select-none">{t('common.selectAllCurrent')}</span>
          </label>
          <Button
            variant="danger"
            size="sm"
            onClick={() => setConfirmOpen(true)}
            disabled={selectedCount === 0 || isDeleting}
            isLoading={isDeleting}
            className="disabled:!border-transparent disabled:!bg-transparent"
          >
            {isDeleting ? t('common.deleting') : t('common.delete')}
          </Button>
        </div>
      ) : null}
      {deleteFailed ? (
        <InlineAlert
          variant="danger"
          message={t('stockBar.deleteFailed')}
          className="rounded-xl px-3 py-2 text-xs shadow-none"
        />
      ) : null}
    </>
  );

  const listBody = isLoading ? (
    <DashboardStateBlock
      loading
      compact
      title={t('stockBar.loading')}
    />
  ) : items.length === 0 ? (
    <DashboardStateBlock
      title={t('stockBar.emptyTitle')}
      description={t('stockBar.emptyDescription')}
      icon={(
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      )}
    />
  ) : (
    <div className="space-y-1.5">
      {orderedItems.map((item) => {
        const code = item.stockCode || '';
        const isMarket = isMarketReview(code);
        const isSelected = selectedRecordId === item.id || selectedStockCode === code;

        return (
          <div key={`${code}-${item.id}`} className="flex items-center gap-2 group">
            {editMode && onDeleteStock ? (
              <input
                type="checkbox"
                checked={selectedCodes.has(code)}
                onChange={() => toggleCode(code)}
                disabled={isDeleting}
                aria-label={t('history.deleteRecord', { name: item.stockName || code })}
                className="h-3.5 w-3.5 shrink-0 cursor-pointer rounded border-subtle-hover bg-transparent accent-primary focus:ring-primary/30 disabled:opacity-50"
              />
            ) : null}
            <StockBarItemComponent
              item={item}
              isViewing={isSelected}
              onClick={onItemClick}
              isMarketReview={isMarket}
              quote={isMarket ? undefined : quotes?.get(stockQuoteKey(code))}
              marketLightLabel={isMarket ? marketLightLabel : undefined}
              marketReviewRegionLabel={isMarket ? marketReviewRegionLabel : undefined}
            />
          </div>
        );
      })}
    </div>
  );

  const confirmDialog = (
    <ConfirmDialog
      isOpen={confirmOpen}
      title={t('stockBar.deleteConfirmTitle')}
      message={t('stockBar.deleteConfirmMessage', { count: selectedCount })}
      confirmText={t('common.delete')}
      isDanger
      onConfirm={() => void handleDeleteSelected()}
      onCancel={() => setConfirmOpen(false)}
    />
  );

  if (isList) {
    return (
      <div data-testid="home-stock-bar" className={`flex min-h-0 flex-col ${className}`}>
        <div className="space-y-1.5 border-b border-subtle px-3 pb-2 pt-1.5 sm:px-4">
          <div className="flex h-7 items-center justify-between gap-2">
            {countNode ?? <span />}
            {editToggle}
          </div>
          {controls}
          {editBar}
        </div>
        <ScrollArea
          viewportClassName="px-3 py-3 sm:px-4 overscroll-y-contain touch-pan-y"
          className="min-h-0 flex-1"
          testId="home-stock-bar-scroll"
        >
          {listBody}
        </ScrollArea>
        {confirmDialog}
      </div>
    );
  }

  return (
    <aside
      data-testid="home-stock-bar"
      className={`glass-card home-stock-scroll-shell flex min-h-0 flex-col ${className}`}
    >
      <ScrollArea
        viewportClassName="p-3 overscroll-y-contain touch-pan-y"
        testId="home-stock-bar-scroll"
      >
        <div className="mb-3 space-y-2">
          <DashboardPanelHeader
            className="mb-0"
            title={t('stockBar.title')}
            titleClassName="text-sm font-medium"
            headingClassName="items-center"
            actions={(
              <div className="flex items-center gap-1.5">
                {countNode}
                {editToggle}
              </div>
            )}
          />
          {controls}
          {editBar}
        </div>
        {listBody}
      </ScrollArea>
      {confirmDialog}
    </aside>
  );
};
