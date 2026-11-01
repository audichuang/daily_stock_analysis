import React, { useEffect, useRef, useState } from 'react';
import { cn } from '../../utils/cn';
import { NO_VALUE } from '../../utils/format';

export type SortDirection = 'asc' | 'desc';
export interface SortState {
  key: string;
  direction: SortDirection;
}

export interface DataTableColumn<T> {
  key: string;
  header: React.ReactNode;
  /** 儲存格內容；不給就讀 row[key]。 */
  render?: (row: T) => React.ReactNode;
  align?: 'left' | 'right' | 'center';
  /** 數字欄：靠右與 tabular 對齊。 */
  numeric?: boolean;
  /** primary 手機仍顯示；secondary（預設）手機收進列內詳情。 */
  priority?: 'primary' | 'secondary';
  minWidth?: number;
  /** 桌機橫捲時固定在左側。 */
  sticky?: boolean;
  /** 有給才可排序；實際排序由呼叫端依 onSortChange 處理（分頁資料要在伺服器排）。 */
  sortable?: boolean;
}

/** 一組列與它的小計；小計依欄位 key 對齊，手機顯示 mobileSummary。 */
export interface DataTableRowGroup<T> {
  key: string;
  rows: T[];
  summaryCells: Record<string, React.ReactNode>;
  mobileSummary: React.ReactNode;
}

interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  density?: 'compact' | 'regular' | 'comfortable';
  /** 有給就依組渲染（每組一段小計），rows 仍要是全部列。 */
  rowGroups?: DataTableRowGroup<T>[];
  /** 反白目前選中的列。 */
  isRowHighlighted?: (row: T) => boolean;
  sort?: SortState | null;
  onSortChange?: (sort: SortState) => void;
  /** 整列沒有資料（例如報價失敗）：淡化並停用點擊。 */
  isRowUnavailable?: (row: T) => boolean;
  onRowClick?: (row: T) => void;
  /** 桌機列展開：expandedRowKey 符合的列下方多渲染一列，內容由 renderExpandedRow 給。 */
  expandedRowKey?: string | null;
  renderExpandedRow?: (row: T) => React.ReactNode;
  /** 手機自訂卡片列，給了就取代 primary 欄＋詳情的預設呈現。 */
  renderMobileCard?: (row: T) => React.ReactNode;
  emptyState?: React.ReactNode;
  /** 桌機表格的高度上限，超過時表格內部捲動、表頭固定；不給就隨整頁捲動，表頭貼在狀態列下方。 */
  maxHeight?: number | string;
  className?: string;
  'aria-label'?: string;
}

const ROW_HEIGHT = { compact: 'h-9', regular: 'h-[46px]', comfortable: 'h-12' } as const;

const alignClass = <T,>(column: DataTableColumn<T>): string => {
  if (column.align === 'center') return 'text-center';
  if (column.align === 'right' || column.numeric) return 'text-right';
  return 'text-left';
};

const cellContent = <T,>(column: DataTableColumn<T>, row: T): React.ReactNode => {
  if (column.render) return column.render(row);
  const value = (row as Record<string, unknown>)[column.key];
  return value === null || value === undefined ? NO_VALUE : (value as React.ReactNode);
};

const ariaSort = (active: boolean, direction?: SortDirection): 'ascending' | 'descending' | 'none' => {
  if (!active) return 'none';
  return direction === 'asc' ? 'ascending' : 'descending';
};

/**
 * 通用資料表：桌機是表格，手機只顯示 primary 欄，其餘收進點開的列內詳情。
 * 兩種版面都會渲染，靠 CSS 斷點切換，避免 resize 時重新掛載與 SSR 判斷。
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  density = 'comfortable',
  rowGroups,
  isRowHighlighted,
  sort,
  onSortChange,
  isRowUnavailable,
  onRowClick,
  expandedRowKey,
  renderExpandedRow,
  renderMobileCard,
  emptyState,
  maxHeight,
  className = '',
  'aria-label': ariaLabel,
}: DataTableProps<T>): React.ReactElement {
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const desktopRef = useRef<HTMLDivElement>(null);
  const [wide, setWide] = useState(false);

  // overflow-x-clip keeps the header sticky to the page, but a table wider than its box would lose its
  // right-hand columns. Measure and fall back to a horizontal scroller only when it really overflows.
  useEffect(() => {
    const el = desktopRef.current;
    if (!el) return undefined;
    const measure = () => setWide(el.scrollWidth > el.clientWidth + 1);
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    if (el.firstElementChild) observer.observe(el.firstElementChild);
    return () => observer.disconnect();
  }, [rows.length, columns.length]);

  if (rows.length === 0 && emptyState) {
    return <div className={className}>{emptyState}</div>;
  }

  const primaryColumns = columns.filter((column) => column.priority === 'primary');
  const secondaryColumns = columns.filter((column) => column.priority !== 'primary');

  const toggleSort = (column: DataTableColumn<T>) => {
    const isActive = sort?.key === column.key;
    onSortChange?.({ key: column.key, direction: isActive && sort?.direction === 'desc' ? 'asc' : 'desc' });
  };

  const sections: Array<{ key: string; rows: T[]; group?: DataTableRowGroup<T> }> = rowGroups
    ? rowGroups.map((group) => ({ key: group.key, rows: group.rows, group }))
    : [{ key: 'all', rows }];

  return (
    <div className={className}>
      {/* With maxHeight the header sticks inside this scroll box. Without it, overflow-x-clip avoids
          creating a scroll container, so the header sticks to the page below the shell status bar. */}
      <div
        ref={desktopRef}
        data-testid="data-table-desktop"
        style={maxHeight ? { maxHeight } : undefined}
        className={cn('hidden md:block', maxHeight ? 'overflow-auto' : wide ? 'overflow-x-auto' : 'overflow-x-clip')}
      >
        <table className="w-full border-collapse text-sm" aria-label={ariaLabel}>
          <thead className={cn('sticky z-10 bg-card', maxHeight ? 'top-0' : 'top-[calc(var(--shell-header-height)+var(--shell-status-height))]')}>
            <tr className="border-b border-border/60 text-xs text-secondary-text">
              {columns.map((column) => {
                const isActive = sort?.key === column.key;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    aria-sort={column.sortable ? ariaSort(isActive, sort?.direction) : undefined}
                    style={column.minWidth ? { minWidth: column.minWidth } : undefined}
                    className={cn(
                      'whitespace-nowrap px-3 py-2 font-medium',
                      alignClass(column),
                      column.sticky && 'sticky left-0 z-20 bg-card',
                    )}
                  >
                    {column.sortable ? (
                      <button
                        type="button"
                        className="inline-flex cursor-pointer items-center gap-1 hover:text-foreground"
                        onClick={() => toggleSort(column)}
                      >
                        {column.header}
                        {isActive ? <span aria-hidden="true">{sort?.direction === 'asc' ? '↑' : '↓'}</span> : null}
                      </button>
                    ) : (
                      column.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          {sections.map((section) => (
            <tbody key={section.key}>
              {section.group ? (
                <tr data-row-group={section.key} className={cn(ROW_HEIGHT[density], 'border-b border-border/60 bg-elevated/40 font-medium')}>
                  {columns.map((column) => (
                    <td key={column.key} className={cn('px-3', alignClass(column), column.numeric && 'tabular-nums')}>
                      {section.group?.summaryCells[column.key] ?? null}
                    </td>
                  ))}
                </tr>
              ) : null}
              {section.rows.map((row) => {
                const unavailable = isRowUnavailable?.(row) ?? false;
                const clickable = Boolean(onRowClick) && !unavailable;
                const highlighted = isRowHighlighted?.(row) ?? false;
                const key = rowKey(row);
                const expandedContent = renderExpandedRow && expandedRowKey === key ? renderExpandedRow(row) : null;
                return (
                  <React.Fragment key={key}>
                  <tr
                    data-row-key={key}
                    data-row-state={unavailable ? 'unavailable' : 'available'}
                    data-row-highlighted={highlighted || undefined}
                    onClick={clickable ? () => onRowClick?.(row) : undefined}
                    className={cn(
                      ROW_HEIGHT[density],
                      'border-b border-border/40',
                      clickable && 'cursor-pointer hover:bg-hover',
                      unavailable && 'opacity-50',
                      highlighted && 'bg-cyan/10',
                    )}
                  >
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className={cn(
                          'px-3',
                          alignClass(column),
                          column.numeric && 'tabular-nums',
                          column.sticky && 'sticky left-0 bg-card',
                        )}
                      >
                        {cellContent(column, row)}
                      </td>
                    ))}
                  </tr>
                  {expandedContent ? (
                    <tr data-row-state="expanded" data-testid="data-table-expanded-row" className="border-b border-border/40">
                      <td colSpan={columns.length} className="p-0">
                        {expandedContent}
                      </td>
                    </tr>
                  ) : null}
                  </React.Fragment>
                );
              })}
            </tbody>
          ))}
        </table>
      </div>

      <ul data-testid="data-table-mobile" className="divide-y divide-border/40 md:hidden">
        {sections.flatMap((section) => [
          ...(section.group ? [
            <li key={`group-${section.key}`} data-row-group={section.key} className="bg-elevated/40 px-3 py-2 text-xs font-medium">
              {section.group.mobileSummary}
            </li>,
          ] : []),
          ...section.rows.map((row) => {
          const key = rowKey(row);
          const unavailable = isRowUnavailable?.(row) ?? false;
          const highlighted = isRowHighlighted?.(row) ?? false;
          if (renderMobileCard) {
            return (
              <li key={key} data-row-key={key} data-row-highlighted={highlighted || undefined} data-row-state={unavailable ? 'unavailable' : 'available'} className={cn(unavailable && 'opacity-50', highlighted && 'bg-cyan/10')}>
                {renderMobileCard(row)}
              </li>
            );
          }
          const expanded = expandedKey === key;
          return (
            <li key={key} data-row-key={key} data-row-highlighted={highlighted || undefined} data-row-state={unavailable ? 'unavailable' : 'available'} className={cn(unavailable && 'opacity-50', highlighted && 'bg-cyan/10')}>
              <button
                type="button"
                aria-expanded={secondaryColumns.length > 0 ? expanded : undefined}
                disabled={secondaryColumns.length === 0}
                onClick={() => setExpandedKey(expanded ? null : key)}
                className={cn('flex min-h-11 w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm', secondaryColumns.length > 0 && 'cursor-pointer')}
              >
                {primaryColumns.map((column) => (
                  <span key={column.key} className={cn('min-w-0', alignClass(column), column.numeric && 'tabular-nums')}>
                    {cellContent(column, row)}
                  </span>
                ))}
              </button>
              {expanded ? (
                <dl className="grid grid-cols-2 gap-x-3 gap-y-2 px-3 pb-3 text-xs">
                  {secondaryColumns.map((column) => (
                    <div key={column.key} className="min-w-0">
                      <dt className="text-secondary-text">{column.header}</dt>
                      <dd className={cn('mt-0.5 text-foreground', column.numeric && 'tabular-nums')}>{cellContent(column, row)}</dd>
                    </div>
                  ))}
                </dl>
              ) : null}
            </li>
          );
          }),
        ])}
      </ul>
    </div>
  );
}
