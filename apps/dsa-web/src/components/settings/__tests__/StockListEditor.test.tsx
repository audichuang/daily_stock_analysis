import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { StockListEditor } from '../StockListEditor';

vi.mock('../../StockAutocomplete', () => ({
  StockAutocomplete: ({
    id,
    value,
    onChange,
    onSubmit,
  }: {
    id?: string;
    value: string;
    onChange: (value: string) => void;
    onSubmit: (code: string, name?: string, source?: 'manual' | 'autocomplete') => void;
  }) => (
    <>
      <input id={id} aria-label="search" value={value} onChange={(event) => onChange(event.target.value)} />
      <button type="button" onClick={() => onSubmit(value)}>manual submit</button>
      <button type="button" onClick={() => onSubmit('2330.TW', '台積電', 'autocomplete')}>pick suggestion</button>
    </>
  ),
}));

function setup(value: string) {
  const onChange = vi.fn();
  render(<StockListEditor id="setting-STOCK_LIST" value={value} onChange={onChange} />);
  return onChange;
}

describe('StockListEditor', () => {
  it('shows one row per stock and the count', () => {
    setup('2330.TW,AAPL');
    expect(screen.getByText('2330.TW')).toBeInTheDocument();
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('共 2 只')).toBeInTheDocument();
  });

  it('adds a picked suggestion keeping the comma-separated format', () => {
    const onChange = setup('AAPL');
    fireEvent.click(screen.getByRole('button', { name: 'pick suggestion' }));
    expect(onChange).toHaveBeenCalledWith('AAPL,2330.TW');
  });

  it('adds a manually typed valid code in upper case and clears the search box', () => {
    const onChange = setup('AAPL');
    const search = screen.getByLabelText('search');
    fireEvent.change(search, { target: { value: 'msft' } });
    fireEvent.click(screen.getByRole('button', { name: 'manual submit' }));
    expect(onChange).toHaveBeenCalledWith('AAPL,MSFT');
    expect(search).toHaveValue('');
  });

  it('rejects a typed stock name instead of writing it into STOCK_LIST', () => {
    const onChange = setup('AAPL');
    fireEvent.change(screen.getByLabelText('search'), { target: { value: '台積電' } });
    fireEvent.click(screen.getByRole('button', { name: 'manual submit' }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent('台積電');
  });

  it('does not add a duplicate regardless of case', () => {
    const onChange = setup('2330.TW');
    fireEvent.click(screen.getByRole('button', { name: 'pick suggestion' }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent('2330.TW');
  });

  it('moves rows with up and down, changing only the order', () => {
    const onChange = setup('A,B,C');
    fireEvent.click(screen.getByRole('button', { name: '上移 C' }));
    expect(onChange).toHaveBeenLastCalledWith('A,C,B');
    fireEvent.click(screen.getByRole('button', { name: '下移 A' }));
    expect(onChange).toHaveBeenLastCalledWith('B,A,C');
  });

  it('disables moving past either end', () => {
    setup('A,B');
    expect(screen.getByRole('button', { name: '上移 A' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '下移 B' })).toBeDisabled();
  });

  it('removes a row', () => {
    const onChange = setup('A,B,C');
    fireEvent.click(screen.getByRole('button', { name: '移除 B' }));
    expect(onChange).toHaveBeenCalledWith('A,C');
  });

  it('normalizes legacy separators only when the list is edited, and keeps the raw text editable', () => {
    const onChange = setup('A，B、C');
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('textbox', { name: '原文', hidden: true })).toHaveValue('A，B、C');
    fireEvent.click(screen.getByRole('button', { name: '移除 B' }));
    expect(onChange).toHaveBeenCalledWith('A,C');
  });

  it('passes the raw text through unchanged', () => {
    const onChange = setup('A');
    fireEvent.change(screen.getByRole('textbox', { name: '原文', hidden: true }), { target: { value: 'A B' } });
    expect(onChange).toHaveBeenCalledWith('A B');
  });
});
