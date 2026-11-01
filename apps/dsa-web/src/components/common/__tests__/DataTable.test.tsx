import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DataTable, type DataTableColumn } from '../DataTable';

interface Row {
  code: string;
  price: number | null;
  sector: string;
}

const columns: DataTableColumn<Row>[] = [
  { key: 'code', header: '代號', priority: 'primary', sticky: true, sortable: true },
  { key: 'price', header: '現價', priority: 'primary', numeric: true, sortable: true },
  { key: 'sector', header: '產業', minWidth: 120 },
];

const rows: Row[] = [
  { code: '2330.TW', price: 1005, sector: '半導體' },
  { code: 'AAPL', price: null, sector: '科技' },
];

const setup = (props: Partial<React.ComponentProps<typeof DataTable<Row>>> = {}) =>
  render(<DataTable columns={columns} rows={rows} rowKey={(row) => row.code} {...props} />);

const desktop = () => within(screen.getByTestId('data-table-desktop'));
const mobile = () => within(screen.getByTestId('data-table-mobile'));

describe('DataTable 桌機', () => {
  it('點表頭送出排序：預設遞減、再點遞增', () => {
    const onSortChange = vi.fn();
    const { rerender } = setup({ onSortChange });
    fireEvent.click(desktop().getByRole('button', { name: '現價' }));
    expect(onSortChange).toHaveBeenLastCalledWith({ key: 'price', direction: 'desc' });

    rerender(
      <DataTable columns={columns} rows={rows} rowKey={(row) => row.code} onSortChange={onSortChange} sort={{ key: 'price', direction: 'desc' }} />,
    );
    expect(desktop().getByRole('columnheader', { name: /現價/ })).toHaveAttribute('aria-sort', 'descending');
    fireEvent.click(desktop().getByRole('button', { name: /現價/ }));
    expect(onSortChange).toHaveBeenLastCalledWith({ key: 'price', direction: 'asc' });
  });

  it('不可排序的欄沒有按鈕', () => {
    setup();
    expect(desktop().queryByRole('button', { name: '產業' })).not.toBeInTheDocument();
  });

  it('density 對應 36 與 48px 列高', () => {
    const { unmount } = setup({ density: 'compact' });
    expect(desktop().getAllByRole('row')[1]).toHaveClass('h-9');
    unmount();
    setup({ density: 'comfortable' });
    expect(desktop().getAllByRole('row')[1]).toHaveClass('h-12');
  });

  it('數字欄靠右 tabular，缺值顯示 — 而不是 0', () => {
    setup();
    const cell = desktop().getByRole('cell', { name: '—' });
    expect(cell).toHaveClass('text-right', 'tabular-nums');
  });

  it('0 是真實讀數，不當缺值', () => {
    setup({ rows: [{ code: 'X', price: 0, sector: 'y' }] });
    expect(desktop().getByRole('cell', { name: '0' })).toBeInTheDocument();
  });

  it('表頭與 sticky 欄固定，minWidth 生效', () => {
    setup();
    expect(desktop().getAllByRole('rowgroup')[0]).toHaveClass('sticky', 'top-[calc(var(--shell-header-height)+var(--shell-status-height))]');
    expect(desktop().getByRole('columnheader', { name: '代號' })).toHaveClass('sticky', 'left-0');
    expect(desktop().getByRole('columnheader', { name: '產業' })).toHaveStyle({ minWidth: '120px' });
  });

  it('沒給 maxHeight 時不建立內層垂直捲動，表頭貼在狀態列下方', () => {
    setup();
    const container = screen.getByTestId('data-table-desktop');
    expect(container).toHaveClass('overflow-x-clip');
    expect(container).not.toHaveClass('overflow-y-auto');
    expect(container).not.toHaveClass('overflow-auto');
    expect(container).not.toHaveClass('overflow-x-auto');
    expect(container.style.maxHeight).toBe('');
  });

  it('表格比容器寬時改成可橫向捲動，才拿得到右側欄位', () => {
    const widthSpy = vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(1029);
    const clientSpy = vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(702);
    try {
      setup();
      const container = screen.getByTestId('data-table-desktop');
      expect(container).toHaveClass('overflow-x-auto');
      expect(container).not.toHaveClass('overflow-x-clip');
    } finally {
      widthSpy.mockRestore();
      clientSpy.mockRestore();
    }
  });

  it('有給 maxHeight 時維持內層捲動、表頭貼容器頂端', () => {
    setup({ maxHeight: 320 });
    const container = screen.getByTestId('data-table-desktop');
    expect(container).toHaveClass('overflow-auto');
    expect(container).toHaveStyle({ maxHeight: '320px' });
    expect(desktop().getAllByRole('rowgroup')[0]).toHaveClass('sticky', 'top-0');
  });

  it('整列 unavailable 淡化且不能點', () => {
    const onRowClick = vi.fn();
    setup({ onRowClick, isRowUnavailable: (row) => row.price === null });
    const [, available, unavailable] = desktop().getAllByRole('row');
    expect(unavailable).toHaveAttribute('data-row-state', 'unavailable');
    expect(unavailable).toHaveClass('opacity-50');
    fireEvent.click(unavailable);
    expect(onRowClick).not.toHaveBeenCalled();
    fireEvent.click(available);
    expect(onRowClick).toHaveBeenCalledWith(rows[0]);
  });
});

describe('DataTable 手機', () => {
  it('只顯示 primary 欄，次要欄收在詳情', () => {
    setup();
    expect(mobile().getByText('2330.TW')).toBeInTheDocument();
    expect(mobile().queryByText('半導體')).not.toBeInTheDocument();
  });

  it('點開列顯示次要欄，再點收合，同時只開一列', () => {
    setup();
    const [first, second] = mobile().getAllByRole('button');
    fireEvent.click(first);
    expect(first).toHaveAttribute('aria-expanded', 'true');
    expect(mobile().getByText('半導體')).toBeInTheDocument();

    fireEvent.click(second);
    expect(mobile().queryByText('半導體')).not.toBeInTheDocument();
    expect(mobile().getByText('科技')).toBeInTheDocument();

    fireEvent.click(second);
    expect(mobile().queryByText('科技')).not.toBeInTheDocument();
  });

  it('支援自訂卡片列', () => {
    setup({ renderMobileCard: (row) => <div>卡片 {row.code}</div> });
    expect(mobile().getByText('卡片 AAPL')).toBeInTheDocument();
    expect(mobile().queryByRole('button')).not.toBeInTheDocument();
  });

  it('整列 unavailable 同樣標示', () => {
    setup({ isRowUnavailable: (row) => row.price === null });
    expect(mobile().getAllByRole('listitem')[1]).toHaveAttribute('data-row-state', 'unavailable');
  });
});

describe('DataTable 空資料', () => {
  it('顯示 emptyState，不渲染表格', () => {
    setup({ rows: [], emptyState: <p>沒有資料</p> });
    expect(screen.getByText('沒有資料')).toBeInTheDocument();
    expect(screen.queryByTestId('data-table-desktop')).not.toBeInTheDocument();
  });

  it('renders an expanded row only for the matching key', () => {
    setup({ expandedRowKey: 'AAPL', renderExpandedRow: (row) => <span>detail {row.code}</span> });

    const expanded = within(screen.getByTestId('data-table-desktop')).getAllByTestId('data-table-expanded-row');
    expect(expanded).toHaveLength(1);
    expect(expanded[0]).toHaveTextContent('detail AAPL');
    expect(expanded[0].querySelector('td')).toHaveAttribute('colspan', String(columns.length));
  });

  it('renders no expanded row without a key', () => {
    setup({ renderExpandedRow: (row) => <span>detail {row.code}</span> });

    expect(screen.queryByTestId('data-table-expanded-row')).not.toBeInTheDocument();
  });
});
