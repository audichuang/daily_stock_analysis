import type React from 'react';
import { useEffect, useState } from 'react';
import { useTheme } from 'next-themes';
import { stocksApi } from '../../api/stocks';
import { getParsedApiError } from '../../api/error';
import { Drawer } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

interface StockDossierDrawerProps {
  stockCode: string;
  stockName?: string | null;
  onClose: () => void;
}

/**
 * 台股四維度分析報告：先載入純數字版（快），再等 LLM 解讀版，到了就替換。
 * 報告是伺服器渲染的獨立 HTML，放在不執行腳本的 sandbox iframe 裡。
 */
export const StockDossierDrawer: React.FC<StockDossierDrawerProps> = ({ stockCode, stockName, onClose }) => {
  const { t } = useUiLanguage();
  const { resolvedTheme } = useTheme();
  const theme = resolvedTheme === 'light' ? 'light' : 'dark';
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 以「代碼＋主題」當請求識別：切主題重抓時識別改變，等待提示自然重新出現（不必在 effect 裡同步 setState）
  const requestKey = `${stockCode}|${theme}`;
  const [settledKey, setSettledKey] = useState<string | null>(null);
  const narrativePending = settledKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    // 先拿純數字版；解讀版排在後面，後端可直接用剛建好的資料包快取，不重查分點
    stocksApi
      .getDossierHtml(stockCode, { theme })
      .then((page) => {
        if (cancelled) return undefined;
        setHtml(page);
        return stocksApi.getDossierHtml(stockCode, { theme, narrative: true }).then(
          (withNarrative) => {
            if (!cancelled) setHtml(withNarrative);
          },
          () => undefined, // 解讀失敗時保留純數字版
        );
      })
      .catch((err) => {
        if (!cancelled) setError(getParsedApiError(err).message);
      })
      .finally(() => {
        if (!cancelled) setSettledKey(requestKey);
      });
    return () => {
      cancelled = true;
    };
  }, [stockCode, theme, requestKey]);

  return (
    <Drawer
      isOpen
      onClose={onClose}
      title={`${[stockName, stockCode].filter(Boolean).join(' ')} · ${t('home.dossier')}`}
      width="max-w-5xl"
      zIndex={100}
    >
      {narrativePending && html ? (
        <p className="mb-3 text-xs text-muted-text" role="status">{t('home.dossierNarrativePending')}</p>
      ) : null}
      {error && !html ? (
        <p className="text-sm text-danger" role="alert">{error}</p>
      ) : html ? (
        <iframe
          title={t('home.dossier')}
          sandbox=""
          srcDoc={html}
          className="h-[calc(100vh-10rem)] w-full rounded-lg border border-border/60"
        />
      ) : (
        <p className="text-sm text-muted-text" role="status">{t('home.dossierLoading')}</p>
      )}
    </Drawer>
  );
};
