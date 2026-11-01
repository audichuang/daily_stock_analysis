import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Search } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { StockAutocomplete } from '../StockAutocomplete';

const SearchDialog: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const { t } = useUiLanguage();
  const navigate = useNavigate();
  const [value, setValue] = useState('');
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    containerRef.current?.querySelector('input')?.focus();
  }, []);

  // 狀態列是 sticky 的堆疊環境，不 portal 會被側欄蓋住。
  return createPortal(
    <div className="fixed inset-0 z-[80] bg-background/70 backdrop-blur-sm" role="presentation" onClick={onClose}>
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('layout.search.open')}
        className="mx-auto mt-24 w-full max-w-xl rounded-2xl border border-border/70 bg-card p-3 shadow-soft-card"
        onClick={(event) => event.stopPropagation()}
      >
        <StockAutocomplete
          value={value}
          onChange={setValue}
          placeholder={t('layout.search.placeholder')}
          ariaLabel={t('layout.search.open')}
          onSubmit={(code) => {
            const target = code.trim();
            if (!target) {
              return;
            }
            onClose();
            navigate(`/?stock=${encodeURIComponent(target)}`);
          }}
        />
      </div>
    </div>,
    document.body,
  );
};

/** 桌機全站搜尋：對話框開啟時才掛載，股票索引不會在每頁一進來就載入。 */
export const GlobalStockSearch: React.FC = () => {
  const { t } = useUiLanguage();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setOpen(true);
      } else if (event.key === 'Escape') {
        setOpen(false);
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex h-6 shrink-0 items-center gap-1.5 rounded-lg border border-border/70 px-2 text-xs text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
      >
        <Search className="h-3.5 w-3.5" aria-hidden="true" />
        <span>{t('layout.search.open')}</span>
        <kbd className="font-sans text-[10px] text-muted-text">⌘K</kbd>
      </button>
      {open ? <SearchDialog onClose={() => setOpen(false)} /> : null}
    </>
  );
};
