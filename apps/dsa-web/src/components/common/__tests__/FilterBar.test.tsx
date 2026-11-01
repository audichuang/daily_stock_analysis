import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Button } from '../Button';
import { Input } from '../Input';
import { Segmented } from '../Segmented';
import { Select } from '../Select';
import { FilterBar } from '../Toolbar';

describe('FilterBar', () => {
  it('桌機直接顯示次要條件；手機版收起，按鈕顯示已套用數', () => {
    render(<FilterBar primary={<span>市場</span>} secondary={<span>產業條件</span>} activeCount={2} />);
    const inline = screen.getByTestId('filter-bar-secondary-inline');
    expect(inline).toHaveClass('hidden', 'md:flex');
    expect(within(inline).getByText('產業條件')).toBeInTheDocument();

    const trigger = screen.getByTestId('filter-bar-more');
    expect(trigger).toHaveClass('md:hidden');
    expect(trigger).toHaveTextContent('2');
  });

  it('手機點開 Drawer 才看得到次要條件', () => {
    render(<FilterBar primary={<span>市場</span>} secondary={<span>產業條件</span>} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('filter-bar-more'));
    expect(within(screen.getByRole('dialog')).getByText('產業條件')).toBeInTheDocument();
  });

  it('沒有套用條件時不顯示 0', () => {
    render(<FilterBar secondary={<span>條件</span>} activeCount={0} />);
    expect(screen.getByTestId('filter-bar-more')).not.toHaveTextContent('0');
  });

  it('沒有次要條件就不出現篩選按鈕', () => {
    render(<FilterBar primary={<span>市場</span>} actions={<button>匯出</button>} />);
    expect(screen.queryByTestId('filter-bar-more')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '匯出' })).toBeInTheDocument();
  });
});

describe('控制項同高', () => {
  it('Input、Select、Button md 都是 36px', () => {
    render(
      <>
        <Input aria-label="輸入" />
        <Select label="選擇" value="a" onChange={() => undefined} options={[{ value: 'a', label: 'A' }]} />
        <Button>按鈕</Button>
      </>,
    );
    expect(screen.getByRole('textbox', { name: '輸入' })).toHaveClass('h-9');
    expect(screen.getByRole('combobox')).toHaveClass('h-9');
    expect(screen.getByRole('button', { name: '按鈕' })).toHaveClass('h-9');
  });

  it('登入頁的輸入框維持大尺寸', () => {
    render(<Input aria-label="密碼" appearance="login" />);
    expect(screen.getByRole('textbox', { name: '密碼' })).toHaveClass('h-11');
  });
});

describe('Segmented', () => {
  const options = [
    { value: 'tw', label: '台股' },
    { value: 'us', label: '美股' },
    { value: 'off', label: '關閉', disabled: true },
  ];

  it('點選切換，選取狀態正確', () => {
    const onChange = vi.fn();
    render(<Segmented aria-label="市場" value="tw" onChange={onChange} options={options} />);
    expect(screen.getByRole('radio', { name: '台股' })).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(screen.getByRole('radio', { name: '美股' }));
    expect(onChange).toHaveBeenCalledWith('us');
  });

  it('方向鍵移動且跳過停用項', () => {
    const onChange = vi.fn();
    render(<Segmented aria-label="市場" value="us" onChange={onChange} options={options} />);
    fireEvent.keyDown(screen.getByRole('radiogroup'), { key: 'ArrowRight' });
    expect(onChange).toHaveBeenCalledWith('tw');
  });

  it('停用項不能點', () => {
    const onChange = vi.fn();
    render(<Segmented aria-label="市場" value="tw" onChange={onChange} options={options} />);
    fireEvent.click(screen.getByRole('radio', { name: '關閉' }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
