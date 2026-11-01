import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { BarChart3, ChevronDown, Clipboard, FileText, Gauge, RotateCcw, ShieldAlert, Target, TrendingUp, WalletCards, Workflow } from 'lucide-react';
import { historyApi } from '../../api/history';
import { formatUiText, UI_TEXT } from '../../i18n/uiText';
import { getMarketReviewUiText } from '../../locales/marketReviewText';
import type {
  AnalysisReport,
  MarketReviewIndexTrend,
  MarketReviewPayload,
  MarketReviewPayloadSection,
  MarketReviewRegion,
  ReportLanguage,
} from '../../types/analysis';
import { formatDateTime, formatNumber, formatPercent } from '../../utils/format';
import { markdownToPlainText } from '../../utils/markdown';
import { marketToneClass } from '../../utils/marketTone';
import { splitLeadingEmoji } from '../../utils/reportMarkdown';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { Button, Card, Change, Segmented, Tooltip } from '../common';
import { ActionMenu, type ActionMenuItem } from '../common/ActionMenu';
import { ReportMarkdownBody } from './ReportMarkdownBody';
import { ShareImageButton } from './ShareImageButton';

interface MarketReviewReportViewProps {
  report?: AnalysisReport;
  recordId?: number;
  content?: string;
  payload?: MarketReviewPayload | null;
  reportLanguage?: ReportLanguage;
  className?: string;
  onOpenRunFlow?: (recordId: number) => void;
  /** Shows a "full report" button in the hero (history view opens the markdown drawer). */
  onOpenFullReport?: () => void;
  /** Page-level actions merged into the hero's single ⋯ menu. */
  extraActionItems?: ActionMenuItem[];
}

type CopyType = 'markdown' | 'text';
type LoadedMarkdown = {
  recordId: number;
  content: string;
};
type LoadError = {
  recordId: number;
  message: string;
};
type MarketReviewSection = {
  id: string;
  title: string;
  content: string;
  icon: typeof FileText;
  /** 結構化 section 的 key；舊報告靠它找出該提前的計畫段。 */
  key?: string;
};

const isMarketReviewPayload = (value: unknown): value is MarketReviewPayload =>
  Boolean(value && typeof value === 'object');

const TOP_HEADING_PATTERN = /^\s*#\s+(.+?)\s*(?:\n+|$)/;
const SECTION_HEADING_PATTERN = /^(#{2,3})\s+(.+?)\s*$/gm;

const normalizeHeading = (value: string): string =>
  value.trim().replace(/\s+/g, ' ').toLowerCase();

const stripTopHeading = (markdown: string, title?: string): string => {
  const match = markdown.match(TOP_HEADING_PATTERN);
  if (!match) {
    return markdown.trim();
  }

  const heading = normalizeHeading(match[1]);
  const reportTitle = normalizeHeading(title || '');
  const genericTitles = new Set([
    'market review',
    '大盘复盘',
    '大盘复盘详情',
    'a股市场复盘',
    'a 股市场复盘',
  ]);

  if (heading === reportTitle || genericTitles.has(heading)) {
    return markdown.slice(match[0].length).trim();
  }

  return markdown.trim();
};

// 舊報告沒有 next_day_plan 時，用來找出該提前的計畫段落。
const PLAN_TITLE_PATTERN = /明日|交易計畫|交易计划|next.?day|plan/i;

const getSectionIcon = (title: string): typeof FileText => {
  const normalized = normalizeHeading(title);
  if (PLAN_TITLE_PATTERN.test(normalized)) {
    return Target;
  }
  // 比對 LLM 標題，舊報告可能是簡體，用跳脫保留比對能力。
  if (/指\u6570|指數|index|overview|大盘|大盤/.test(normalized)) {
    return BarChart3;
  }
  if (/情绪|情緒|赚钱|賺錢|sentiment|breadth|temperature/.test(normalized)) {
    return Gauge;
  }
  if (/行业|行業|板块|板塊|主题|主題|轮动|輪動|sector|theme|rotation/.test(normalized)) {
    return TrendingUp;
  }
  if (/\u8d44金|資金|成交|量能|flow|turnover|volume|capital/.test(normalized)) {
    return WalletCards;
  }
  if (/风险|風險|机会|機會|观察|觀察|risk|watch|next/.test(normalized)) {
    return ShieldAlert;
  }
  return FileText;
};

// LLM 標題可能帶 🎯 等 emoji：顯示時拿掉，改用 lucide icon；Overview 一律顯示成「摘要」。
const cleanSectionTitle = (title: string, overviewLabel: string): string => {
  const { emoji, rest } = splitLeadingEmoji(title.trim());
  const stripped = (emoji ? rest : title).trim();
  return /^(overview|复盘概览|復盤概覽)$/i.test(stripped) ? overviewLabel : stripped;
};

const splitMarketReviewSections = (markdown: string): MarketReviewSection[] => {
  const matches = Array.from(markdown.matchAll(SECTION_HEADING_PATTERN));
  if (matches.length === 0) {
    return [{
      id: 'full-review',
      title: '复盘正文',
      content: markdown,
      icon: FileText,
    }];
  }

  const intro = markdown.slice(0, matches[0].index).trim();
  const sections: MarketReviewSection[] = intro
    ? [{
        id: 'overview',
        title: '复盘概览',
        content: intro,
        icon: FileText,
      }]
    : [];

  matches.forEach((match, index) => {
    const start = (match.index ?? 0) + match[0].length;
    const end = index + 1 < matches.length ? matches[index + 1].index ?? markdown.length : markdown.length;
    const title = match[2].trim();
    const content = markdown.slice(start, end).trim();
    if (!content) {
      return;
    }
    sections.push({
      id: `${index}-${normalizeHeading(title).replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-').replace(/^-|-$/g, '') || 'section'}`,
      title,
      content,
      icon: getSectionIcon(title),
    });
  });

  return sections;
};

const getPayloadSections = (payload?: MarketReviewPayload | null): MarketReviewSection[] => {
  if (!payload) {
    return [];
  }

  if (payload.markets) {
    return Object.entries(payload.markets).flatMap(([region, marketPayload]) => {
      const marketTitle = marketPayload.title || region.toUpperCase();
      return getPayloadSections(marketPayload).map((section) => ({
        ...section,
        id: `${region}-${section.id}`,
        title: `${marketTitle} / ${section.title}`,
      }));
    });
  }

  const payloadTitle = normalizeHeading(payload.title || '');
  return (payload.sections || [])
    .filter((section: MarketReviewPayloadSection) => section.markdown?.trim())
    .filter((section: MarketReviewPayloadSection) => normalizeHeading(section.title || '') !== payloadTitle)
    .map((section, index) => ({
      id: `${section.key || index}-${normalizeHeading(section.title).replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-') || 'section'}`,
      title: section.title || 'Review',
      content: section.markdown,
      icon: getSectionIcon(section.title || ''),
      key: section.key,
    }));
};

const coerceFiniteNumber = (value: unknown): number | null => {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }

  if (typeof value === 'string' && value.trim()) {
    const normalizedValue = value.trim().replace(/,/g, '');
    const numericText = normalizedValue.endsWith('%')
      ? normalizedValue.slice(0, -1).trim()
      : normalizedValue;
    const parsed = Number(numericText);
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
};

// 舊報告沒有 next_day_plan：這些 key 的段落（消息催化／後市展望／明日交易計畫）提前到計畫卡的位置，
// key 都對不到時再用標題兜底。
const LEGACY_PLAN_SECTION_KEYS = ['news_catalysts', '四_明日交易計畫'];

const findLegacyPlanSection = (sections: MarketReviewSection[]): MarketReviewSection | undefined => {
  for (const key of LEGACY_PLAN_SECTION_KEYS) {
    const matched = sections.find((section) => section.key === key);
    if (matched) return matched;
  }
  return sections.find((section) => PLAN_TITLE_PATTERN.test(section.title));
};
const MARKET_TAB_PRIORITY = ['tw', 'us'];

const orderMarketKeys = (markets: Record<string, MarketReviewPayload>): string[] => {
  const keys = Object.keys(markets);
  return [
    ...MARKET_TAB_PRIORITY.filter((key) => keys.includes(key)),
    ...keys.filter((key) => !MARKET_TAB_PRIORITY.includes(key)),
  ];
};

/** YYYY-MM-DD → MM/DD；不做時區換算，場次日期就是後端給的那天。 */
const formatSessionDate = (value?: string | null): string => {
  const match = /^\d{4}-(\d{2})-(\d{2})/.exec(value ?? '');
  return match ? `${match[1]}/${match[2]}` : '';
};

const trendLookupKey = (code: string): string => code.toLowerCase().replace(/[^a-z0-9]/g, '');

// index_trends 的鍵是指數代號，toCamelCase 會改掉大小寫（TAIEX → taiex），所以兩邊都正規化再比。
const findIndexTrend = (
  trends: MarketReviewPayload['indexTrends'],
  code?: string,
): MarketReviewIndexTrend | undefined => {
  if (!trends || !code) return undefined;
  const target = trendLookupKey(code);
  const matchedKey = Object.keys(trends).find((key) => trendLookupKey(key) === target);
  return matchedKey ? trends[matchedKey] : undefined;
};

const Sparkline: React.FC<{ trend?: MarketReviewIndexTrend; colorClass: string }> = ({ trend, colorClass }) => {
  const closes = (trend?.series ?? []).map((point) => point.close).filter((close) => Number.isFinite(close));
  if (closes.length < 2) return null;
  const width = 72;
  const height = 22;
  const min = Math.min(...closes);
  const span = Math.max(...closes) - min || 1;
  const points = closes
    .map((close, index) => `${((index / (closes.length - 1)) * width).toFixed(1)},${(height - ((close - min) / span) * height).toFixed(1)}`)
    .join(' ');
  return (
    <svg data-testid="index-sparkline" viewBox={`0 0 ${width} ${height}`} width={width} height={height} className={`shrink-0 ${colorClass}`} aria-hidden="true">
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
};

const formatSignedAmount = (value: unknown): string => {
  const numeric = coerceFiniteNumber(value);
  if (numeric === null) return formatNumber(null);
  return `${numeric > 0 ? '+' : ''}${formatNumber(numeric, 2)}`;
};

const hasRankingRows = (rankings?: MarketReviewPayload['sectors']): boolean =>
  Boolean(rankings?.top?.length || rankings?.bottom?.length);

const hasStructuredMarketData = (payload?: MarketReviewPayload | null): boolean =>
  Boolean(payload?.breadth || payload?.indices?.length || hasRankingRows(payload?.sectors) || hasRankingRows(payload?.concepts));

// 美股指數名在後端（上游 us_index_mapping.py）是簡體且被測試釘住；繁中報告在顯示層依代碼換成繁體，
// 歷史紀錄也一併生效。只認代碼，不去改寫名稱字串。
const US_INDEX_ZH_TW_NAMES: Record<string, string> = {
  SPX: '標普500指數',
  GSPC: '標普500指數',
  DJI: '道瓊工業指數',
  DJIA: '道瓊工業指數',
  IXIC: '那斯達克綜合指數',
  NASDAQ: '那斯達克綜合指數',
  NDX: '那斯達克100指數',
  VIX: 'VIX恐慌指數',
  RUT: '羅素2000指數',
  SOX: '費城半導體指數',
};

const getLocalizedIndexName = (
  index: { code?: string | null; name?: string | null },
  language: ReportLanguage,
): string => {
  const name = index.name || index.code || '';
  if (language !== 'zh-TW') {
    return name;
  }
  const code = (index.code || '').trim().toUpperCase().replace(/^\^/, '');
  return US_INDEX_ZH_TW_NAMES[code] ?? name;
};

const MARKET_REVIEW_TEXT: Record<ReportLanguage, {
  reviewSummary: string;
  noReviewSummary: string;
  rotationAndFunds: string;
  riskAndWatch: string;
  advancers: string;
  decliners: string;
  limitUpDown: string;
  turnover: string;
  index: string;
  last: string;
  change: string;
  highLow: string;
  industryBoards: string;
  conceptBoards: string;
  leading: string;
  lagging: string;
  todayConclusion: string;
  moreActions: string;
  retry: string;
  flat: string;
  institutional: string;
  foreignNet: string;
  trustNet: string;
  dealerNet: string;
  totalNet: string;
  nextDayPlan: string;
  stanceOffensive: string;
  stanceBalanced: string;
  stanceDefensive: string;
  focus: string;
  risks: string;
  keyLevels: string;
  sectorBoard: string;
  fullText: string;
  dimBreadth: string;
  dimIndex: string;
  dimLimit: string;
  regionCn: string;
  regionHk: string;
  regionUs: string;
  regionTw: string;
  regionJp: string;
  regionKr: string;
  marketTabs: string;
}> = {
  zh: {
    reviewSummary: '复盘摘要',
    noReviewSummary: '暂无摘要',
    rotationAndFunds: '轮动与资金',
    riskAndWatch: '风险与观察',
    advancers: '上涨家数',
    decliners: '下跌家数',
    limitUpDown: '涨停/跌停',
    turnover: '成交额',
    index: '指数',
    last: '最新',
    change: '涨跌幅',
    highLow: '高/低',
    industryBoards: '行业板块',
    conceptBoards: '概念板块',
    leading: '领涨',
    lagging: '领跌',
    todayConclusion: '今日结论',
    moreActions: '更多操作',
    retry: '重试',
    flat: '平盘',
    institutional: '三大法人',
    foreignNet: '外资',
    trustNet: '投信',
    dealerNet: '自营商',
    totalNet: '合计',
    nextDayPlan: '明日计划',
    stanceOffensive: '偏进攻',
    stanceBalanced: '中性',
    stanceDefensive: '偏防守',
    focus: '关注',
    risks: '风险',
    keyLevels: '关键价位',
    sectorBoard: '类股排行',
    fullText: '完整内容',
    dimBreadth: '广度',
    dimIndex: '指数',
    dimLimit: '涨跌停',
    regionCn: 'A 股',
    regionHk: '港股',
    regionUs: '美股',
    regionTw: '台股',
    regionJp: '日股',
    regionKr: '韩股',
    marketTabs: '选择市场',
  },
  en: {
    reviewSummary: 'Review Summary',
    noReviewSummary: 'No review summary yet',
    rotationAndFunds: 'Rotation & Funds',
    riskAndWatch: 'Risks & Watchlist',
    advancers: 'Advancers',
    decliners: 'Decliners',
    limitUpDown: 'Limit Up/Down',
    turnover: 'Turnover',
    index: 'Index',
    last: 'Last',
    change: 'Change',
    highLow: 'High/Low',
    industryBoards: 'Industry Sectors',
    conceptBoards: 'Concept Themes',
    leading: 'Leading',
    lagging: 'Lagging',
    todayConclusion: "Today's Takeaway",
    moreActions: 'More actions',
    retry: 'Retry',
    flat: 'Unchanged',
    institutional: 'Institutional Flow',
    foreignNet: 'Foreign',
    trustNet: 'Trust',
    dealerNet: 'Dealer',
    totalNet: 'Total',
    nextDayPlan: 'Next-Day Plan',
    stanceOffensive: 'Offensive',
    stanceBalanced: 'Balanced',
    stanceDefensive: 'Defensive',
    focus: 'Focus',
    risks: 'Risks',
    keyLevels: 'Key Levels',
    sectorBoard: 'Sector Ranking',
    fullText: 'Full Text',
    dimBreadth: 'Breadth',
    dimIndex: 'Index',
    dimLimit: 'Limits',
    regionCn: 'China',
    regionHk: 'HK',
    regionUs: 'US',
    regionTw: 'Taiwan',
    regionJp: 'Japan',
    regionKr: 'Korea',
    marketTabs: 'Choose market',
  },
  'zh-TW': {
    reviewSummary: '復盤摘要',
    noReviewSummary: '暫無摘要',
    rotationAndFunds: '輪動與資金',
    riskAndWatch: '風險與觀察',
    advancers: '上漲家數',
    decliners: '下跌家數',
    limitUpDown: '漲停/跌停',
    turnover: '成交額',
    index: '指數',
    last: '最新',
    change: '漲跌幅',
    highLow: '高/低',
    industryBoards: '產業板塊',
    conceptBoards: '概念板塊',
    leading: '領漲',
    lagging: '領跌',
    todayConclusion: '今日結論',
    moreActions: '更多操作',
    retry: '重試',
    flat: '平盤',
    institutional: '三大法人',
    foreignNet: '外資',
    trustNet: '投信',
    dealerNet: '自營商',
    totalNet: '合計',
    nextDayPlan: '明日計畫',
    stanceOffensive: '偏進攻',
    stanceBalanced: '中性',
    stanceDefensive: '偏防守',
    focus: '關注',
    risks: '風險',
    keyLevels: '關鍵價位',
    sectorBoard: '類股排行',
    fullText: '完整內容',
    dimBreadth: '廣度',
    dimIndex: '指數',
    dimLimit: '漲跌停',
    regionCn: 'A 股',
    regionHk: '港股',
    regionUs: '美股',
    regionTw: '台股',
    regionJp: '日股',
    regionKr: '韓股',
    marketTabs: '選擇市場',
  },
  ko: {
    reviewSummary: '리뷰 요약',
    noReviewSummary: '요약 없음',
    rotationAndFunds: '순환과 자금',
    riskAndWatch: '리스크와 관찰',
    advancers: '상승 종목 수',
    decliners: '하락 종목 수',
    limitUpDown: '상한가/하한가',
    turnover: '거래대금',
    index: '지수',
    last: '현재',
    change: '등락률',
    highLow: '고가/저가',
    industryBoards: '업종 섹터',
    conceptBoards: '테마 섹터',
    leading: '강세',
    lagging: '약세',
    todayConclusion: '오늘의 결론',
    moreActions: '더 보기',
    retry: '다시 시도',
    flat: '보합',
    institutional: '기관 수급',
    foreignNet: '외국인',
    trustNet: '투신',
    dealerNet: '자기매매',
    totalNet: '합계',
    nextDayPlan: '다음 거래일 계획',
    stanceOffensive: '공격적',
    stanceBalanced: '중립',
    stanceDefensive: '방어적',
    focus: '관심',
    risks: '리스크',
    keyLevels: '주요 가격대',
    sectorBoard: '업종 순위',
    fullText: '전체 내용',
    dimBreadth: '시장 폭',
    dimIndex: '지수',
    dimLimit: '상하한가',
    regionCn: '중국',
    regionHk: '홍콩',
    regionUs: '미국',
    regionTw: '대만',
    regionJp: '일본',
    regionKr: '한국',
    marketTabs: '시장 선택',
  },
};

export const MarketReviewReportView: React.FC<MarketReviewReportViewProps> = ({
  report,
  recordId,
  content: providedContent,
  payload: providedPayload,
  reportLanguage = 'zh',
  className = '',
  onOpenRunFlow,
  onOpenFullReport,
  extraActionItems = [],
}) => {
  const normalizedReportLanguage = normalizeReportLanguage(reportLanguage);
  const uiText = getMarketReviewUiText(normalizedReportLanguage);
  const text = getReportText(normalizedReportLanguage);
  const runFlowText = UI_TEXT[normalizedReportLanguage === 'ko' ? 'en' : normalizedReportLanguage];
  const marketReviewText = MARKET_REVIEW_TEXT[normalizedReportLanguage];
  const [loadedMarkdown, setLoadedMarkdown] = useState<LoadedMarkdown | null>(null);
  const [loadError, setLoadError] = useState<LoadError | null>(null);
  const [retryVersion, setRetryVersion] = useState(0);
  const [copiedType, setCopiedType] = useState<CopyType | null>(null);
  const [selectedMarket, setSelectedMarket] = useState<string | null>(null);
  const summary = report?.summary;
  const meta = report?.meta;
  const contextPayload = report?.details?.contextSnapshot?.marketReviewPayload;
  const marketReviewPayload = providedPayload ?? (isMarketReviewPayload(contextPayload) ? contextPayload : null);
  const loadedContent = loadedMarkdown && loadedMarkdown.recordId === recordId ? loadedMarkdown.content : '';
  const content = providedContent ?? marketReviewPayload?.markdownReport ?? loadedContent;
  const error = loadError && loadError.recordId === recordId ? loadError.message : null;
  const hasStructuredContent = Boolean(marketReviewPayload?.sections?.length || marketReviewPayload?.markets);
  const isLoading = Boolean(recordId && !providedContent && !hasStructuredContent && loadedMarkdown?.recordId !== recordId && !error);
  const displayTitle = marketReviewPayload?.rootTitle || marketReviewPayload?.title || meta?.stockName || 'Market Review';
  // Payload titles often lead with an emoji (e.g. 🎯); the hero shows a lucide icon instead.
  const heroTitle = splitLeadingEmoji(displayTitle.trim()).rest.trim() || displayTitle;
  const structuredContent = useMemo(
    () => stripTopHeading(content, displayTitle),
    [content, displayTitle],
  );

  const regionLabels: Record<MarketReviewRegion, string> = {
    cn: marketReviewText.regionCn,
    hk: marketReviewText.regionHk,
    us: marketReviewText.regionUs,
    tw: marketReviewText.regionTw,
    jp: marketReviewText.regionJp,
    kr: marketReviewText.regionKr,
  };
  const marketKeys = useMemo(
    () => (marketReviewPayload?.markets ? orderMarketKeys(marketReviewPayload.markets) : []),
    [marketReviewPayload],
  );
  const activeMarketKey = selectedMarket && marketKeys.includes(selectedMarket) ? selectedMarket : marketKeys[0] ?? null;
  // 一次看一個市場：多市場 payload 取選中的那份，單市場就是 payload 本身。
  const activeMarket: MarketReviewPayload | null = activeMarketKey
    ? marketReviewPayload?.markets?.[activeMarketKey] ?? null
    : marketReviewPayload;
  const marketLabel = (key?: string | null, market?: MarketReviewPayload | null): string => {
    const normalized = (key ?? '').toLowerCase() as MarketReviewRegion;
    return regionLabels[normalized] ?? market?.title ?? (key ?? '');
  };
  const sessionDateOf = (market?: MarketReviewPayload | null): string =>
    formatSessionDate(market?.date ?? market?.marketLight?.tradeDate);

  const overviewLabel = uiText.overviewSection;
  const allSections = useMemo(() => {
    const payloadSections = getPayloadSections(activeMarket);
    const rawSections = payloadSections.length > 0 ? payloadSections : splitMarketReviewSections(structuredContent);
    return rawSections.map((section) => {
      const title = cleanSectionTitle(section.title, overviewLabel);
      return { ...section, title, icon: section.icon === FileText ? getSectionIcon(title) : section.icon };
    });
  }, [activeMarket, overviewLabel, structuredContent]);

  const nextDayPlan = activeMarket?.nextDayPlan;
  // 有結構化計畫時段落留在長文裡；沒有才把舊段落提前。
  const legacyPlanSection = nextDayPlan ? undefined : findLegacyPlanSection(allSections);
  const sections = legacyPlanSection ? allSections.filter((section) => section !== legacyPlanSection) : allSections;

  const indices = useMemo(
    () => (activeMarket?.indices ?? []).map((index) => ({
      ...index,
      name: getLocalizedIndexName(index, normalizedReportLanguage),
    })),
    [activeMarket, normalizedReportLanguage],
  );
  const hasStructuredView = Boolean(activeMarket && hasStructuredMarketData(activeMarket));
  const breadth = activeMarket?.breadth;
  const institutional = breadth?.institutionalNet;
  const light = activeMarket?.marketLight;
  const lightHasReading = Boolean(light?.status && light.status !== 'unavailable');
  const sectorItems = activeMarket?.sectorRank?.items ?? [];
  const legacySectorRankings = [activeMarket?.sectors, activeMarket?.concepts].filter(hasRankingRows);

  const canOpenRunFlow = recordId !== undefined && onOpenRunFlow;

  useEffect(() => {
    if (!recordId || providedContent || hasStructuredContent) {
      return undefined;
    }

    let isMounted = true;

    historyApi.getMarkdown(recordId)
      .then((markdownContent) => {
        if (isMounted) {
          setLoadedMarkdown({ recordId, content: markdownContent });
          setLoadError(null);
        }
      })
      .catch((err: unknown) => {
        if (isMounted) {
          setLoadError({
            recordId,
            message: err instanceof Error ? err.message : text.loadReportFailed,
          });
        }
      });

    return () => {
      isMounted = false;
    };
  }, [hasStructuredContent, providedContent, recordId, retryVersion, text.loadReportFailed]);

  const handleCopy = useCallback(async (type: CopyType) => {
    if (!content) {
      return;
    }
    try {
      const value = type === 'markdown' ? content : markdownToPlainText(content);
      await navigator.clipboard.writeText(value);
      setCopiedType(type);
      window.setTimeout(() => setCopiedType(null), 2000);
    } catch (err) {
      console.error('Copy failed:', err);
    }
  }, [content]);

  // One ⋯ menu: page-level actions first, then copy and run flow.
  const actionItems: ActionMenuItem[] = [
    ...extraActionItems,
    {
      key: 'copy-markdown',
      label: text.copyMarkdownSource,
      icon: <Clipboard className="h-4 w-4" aria-hidden="true" />,
      disabled: isLoading || !content || copiedType !== null,
      onSelect: () => void handleCopy('markdown'),
    },
    {
      key: 'copy-text',
      label: text.copyPlainText,
      icon: <FileText className="h-4 w-4" aria-hidden="true" />,
      disabled: isLoading || !content || copiedType !== null,
      onSelect: () => void handleCopy('text'),
    },
    ...(canOpenRunFlow ? [{
      key: 'run-flow',
      label: formatUiText(runFlowText['runFlow.openHistoryAria'], { recordId }),
      icon: <Workflow className="h-4 w-4" aria-hidden="true" />,
      onSelect: () => onOpenRunFlow(recordId),
    }] : []),
  ];

  // Amber / grey semantic tones with words, never red-green fills (those read as price direction).
  const lightText: Record<string, { label: string; className: string }> = {
    green: { label: uiText.lightTailwind, className: 'border-subtle bg-subtle text-foreground' },
    yellow: { label: uiText.lightNeutral, className: 'border-subtle bg-subtle text-secondary-text' },
    red: { label: uiText.lightCaution, className: 'border-warning/30 bg-warning/10 text-warning' },
  };
  const lightStyle = lightHasReading ? lightText[light?.status ?? ''] : undefined;
  const dimensionRows = [
    { key: 'breadth' as const, label: marketReviewText.dimBreadth },
    { key: 'index' as const, label: marketReviewText.dimIndex },
    { key: 'limit' as const, label: marketReviewText.dimLimit },
  ];

  // Dimension scores live in the badge tooltip only; unavailable dimensions are left out.
  const lightDimensionTooltip = lightStyle
    ? dimensionRows
        .filter(({ key }) => light?.dimensions?.[key]?.available)
        .map(({ key, label }) => `${label} ${formatNumber(light?.dimensions?.[key]?.score, 0)}`)
        .join(' · ')
    : '';

  const upCount = coerceFiniteNumber(breadth?.upCount);
  const downCount = coerceFiniteNumber(breadth?.downCount);
  const flatCount = coerceFiniteNumber(breadth?.flatCount);
  const breadthTotal = (upCount ?? 0) + (downCount ?? 0) + (flatCount ?? 0);
  const percentOf = (value: number | null) => `${((value ?? 0) / breadthTotal) * 100}%`;

  const sentimentScore = typeof summary?.sentimentScore === 'number' && Number.isFinite(summary.sentimentScore)
    ? summary.sentimentScore
    : null;
  const rotationView = summary?.operationAdvice?.trim() || null;
  const riskView = summary?.trendPrediction?.trim() || null;
  const conclusionFields = [
    rotationView ? { key: 'rotation', label: marketReviewText.rotationAndFunds, value: rotationView } : null,
    riskView ? { key: 'risk', label: marketReviewText.riskAndWatch, value: riskView } : null,
  ].filter((field): field is { key: string; label: string; value: string } => field !== null);

  const planStance = nextDayPlan?.stance
    ? {
        offensive: marketReviewText.stanceOffensive,
        balanced: marketReviewText.stanceBalanced,
        defensive: marketReviewText.stanceDefensive,
      }[nextDayPlan.stance]
    : null;
  // Badge carries only the light word; stance falls back to the light's own label so the score is shown once.
  const conclusionHeadline = [
    planStance ?? (lightHasReading ? light?.label?.trim() || null : null),
    sentimentScore !== null ? `${uiText.sentimentShort} ${sentimentScore}/100` : null,
  ].filter(Boolean).join(' · ');

  const sessionTitle = activeMarket && activeMarketKey === null
    ? [marketLabel(activeMarket.region, activeMarket), sessionDateOf(activeMarket)].filter(Boolean).join(' ')
    : '';

  return (
    <div className={`animate-fade-in space-y-4 pb-8 ${className}`}>
      <Card variant="highlight" padding="md" className="home-report-hero text-left">
        {/* 手機寬時按鈕列換到下一行：中文標題在 flex 裡可被壓到一字寬，會變成一字一行 */}
        <div className="flex flex-wrap items-start justify-between gap-3" data-testid="market-review-hero-header">
          <div className="min-w-[12rem] flex-1">
            <h2 className="flex items-center gap-2 text-[26px] font-bold leading-tight text-foreground sm:text-[30px]">
              <BarChart3 className="h-6 w-6 shrink-0 text-primary" aria-hidden="true" />
              <span className="min-w-0">{heroTitle}</span>
            </h2>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-text">
              {sessionTitle ? <span data-testid="market-review-session" className="font-medium text-secondary-text">{sessionTitle}</span> : null}
              {meta?.createdAt ? <span>{formatDateTime(meta.createdAt)}</span> : null}
            </div>
          </div>

          <div className="ml-auto flex shrink-0 items-center gap-2">
            {onOpenFullReport ? (
              <Button variant="primary" size="sm" onClick={onOpenFullReport} disabled={recordId === undefined}>
                <FileText className="h-4 w-4" aria-hidden="true" />
                {uiText.fullReport}
              </Button>
            ) : null}
            <ShareImageButton
              recordId={recordId}
              reportTitle={displayTitle}
              reportLanguage={reportLanguage}
            />
            <ActionMenu label={marketReviewText.moreActions} items={actionItems} />
          </div>
        </div>
        {marketKeys.length > 1 ? (
          <Segmented<string>
            className="mt-3"
            aria-label={marketReviewText.marketTabs}
            value={activeMarketKey ?? ''}
            onChange={setSelectedMarket}
            options={marketKeys.map((key) => {
              const market = marketReviewPayload?.markets?.[key];
              return { value: key, label: [marketLabel(key, market), sessionDateOf(market)].filter(Boolean).join(' ') };
            })}
          />
        ) : marketKeys.length === 1 ? (
          <p data-testid="market-review-session" className="mt-2 text-xs font-medium text-secondary-text">
            {[marketLabel(marketKeys[0], activeMarket), sessionDateOf(activeMarket)].filter(Boolean).join(' ')}
          </p>
        ) : null}
      </Card>

      {indices.length > 0 ? (
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4" data-testid="market-index-cards">
          {indices.map((index) => {
            // VIX 漲跌不是多空方向，顯示中性。
            const isVix = /VIX/i.test(index.code ?? '');
            const change = coerceFiniteNumber(index.changePct);
            const directional = isVix ? null : change;
            return (
              <Card key={index.code || index.name} variant="surface" padding="sm" className="min-w-0 text-left">
                <p className="truncate text-xs text-secondary-text">{index.name}</p>
                <div className="mt-1 flex items-end justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-base font-semibold tabular-nums text-foreground">{formatNumber(coerceFiniteNumber(index.current), 2)}</p>
                    <Change value={directional} className="text-xs">{formatPercent(change)}</Change>
                  </div>
                  <Sparkline trend={findIndexTrend(activeMarket?.indexTrends, index.code)} colorClass={marketToneClass(directional)} />
                </div>
              </Card>
            );
          })}
        </div>
      ) : null}

      {summary || lightHasReading ? (
        <Card variant="surface" padding="md" className="text-left" title={marketReviewText.todayConclusion}>
          <div data-testid="market-review-conclusion">
            {lightStyle || conclusionHeadline ? (
              <div className="mb-3 flex flex-wrap items-center gap-2" data-testid="market-light">
                {lightStyle ? (
                  <Tooltip content={lightDimensionTooltip} focusable={Boolean(lightDimensionTooltip)}>
                    <span
                      data-testid="market-light-badge"
                      className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${lightStyle.className}`}
                    >
                      {lightStyle.label}
                    </span>
                  </Tooltip>
                ) : null}
                {conclusionHeadline ? (
                  <span data-testid="market-review-headline" className="text-sm font-semibold text-foreground">{conclusionHeadline}</span>
                ) : null}
              </div>
            ) : null}
            <p className="text-sm leading-6 text-foreground">
              {summary?.analysisSummary || light?.guidance || marketReviewText.noReviewSummary}
            </p>
            {conclusionFields.length > 0 ? (
              <dl className="mt-3 grid grid-cols-1 gap-2 text-sm md:grid-cols-2">
                {conclusionFields.map((field) => (
                  <div key={field.key} className="min-w-0">
                    <dt className="text-xs text-secondary-text">{field.label}</dt>
                    <dd className="mt-0.5 text-foreground">{field.value}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </div>
        </Card>
      ) : null}

      {nextDayPlan || legacyPlanSection ? (
        <Card variant="surface" padding="md" className="text-left">
          <details open data-testid="next-day-plan-card" className="group">
            <summary className="flex cursor-pointer list-none items-center gap-2">
              <Target className="h-4 w-4 text-primary" aria-hidden="true" />
              <h3 className="text-sm font-semibold text-foreground">{marketReviewText.nextDayPlan}</h3>
              <ChevronDown className="ml-auto h-4 w-4 text-secondary-text transition-transform group-open:rotate-180" aria-hidden="true" />
            </summary>
            {nextDayPlan ? (
              <div data-testid="next-day-plan" className="mt-3 space-y-2 text-sm">
                {planStance ? <span className="inline-block rounded-full border border-subtle px-2 py-0.5 text-xs text-secondary-text">{planStance}</span> : null}
                {nextDayPlan.summary ? <p className="leading-6 text-foreground">{nextDayPlan.summary}</p> : null}
                {([
                  [marketReviewText.focus, nextDayPlan.focus],
                  [marketReviewText.risks, nextDayPlan.risks],
                ] as const).map(([label, entries]) => (entries?.length ? (
                  <div key={label}>
                    <p className="text-xs text-secondary-text">{label}</p>
                    <ul className="mt-0.5 list-disc pl-5 text-foreground">
                      {entries.map((entry) => <li key={entry}>{entry}</li>)}
                    </ul>
                  </div>
                ) : null))}
                {nextDayPlan.keyLevels?.length ? (
                  <div>
                    <p className="text-xs text-secondary-text">{marketReviewText.keyLevels}</p>
                    <div className="mt-0.5 flex flex-wrap gap-x-4 gap-y-1">
                      {nextDayPlan.keyLevels.map((level) => (
                        <span key={level.label} className="text-foreground">
                          {level.label} <span className="tabular-nums">{formatNumber(level.price, 2)}</span>
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : legacyPlanSection ? (
              <div data-testid="next-day-plan" className="mt-3">
                <ReportMarkdownBody content={legacyPlanSection.content} className="market-review-markdown" />
              </div>
            ) : null}
          </details>
        </Card>
      ) : null}

      {/* breadth 與法人都來自 breadth；整包沒有就不出空卡 */}
      {breadth ? (
        <Card variant="surface" padding="md" className="space-y-3 text-left">
          {breadthTotal > 0 ? (
            <div data-testid="breadth-bar">
              <div className="flex h-2 overflow-hidden rounded-full bg-subtle" aria-hidden="true">
                <div style={{ width: percentOf(upCount), backgroundColor: 'var(--market-up)' }} />
                <div className="bg-border" style={{ width: percentOf(flatCount) }} />
                <div style={{ width: percentOf(downCount), backgroundColor: 'var(--market-down)' }} />
              </div>
              <div className="mt-1.5 flex flex-wrap justify-between gap-2 text-xs tabular-nums text-secondary-text">
                <span>{marketReviewText.advancers} <span className="text-market-up">{formatNumber(upCount, 0)}</span></span>
                <span>{marketReviewText.flat} {formatNumber(flatCount, 0)}</span>
                <span>{marketReviewText.decliners} <span className="text-market-down">{formatNumber(downCount, 0)}</span></span>
              </div>
            </div>
          ) : null}
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <span className="text-secondary-text">
              {marketReviewText.limitUpDown}{' '}
              <span className="tabular-nums text-foreground">
                {formatNumber(coerceFiniteNumber(breadth.limitUpCount), 0)} / {formatNumber(coerceFiniteNumber(breadth.limitDownCount), 0)}
              </span>
            </span>
            <span className="text-secondary-text">
              {marketReviewText.turnover}{' '}
              <span className="tabular-nums text-foreground">
                {formatNumber(coerceFiniteNumber(breadth.totalAmount), 2)}{breadth.turnoverUnit ? ` ${breadth.turnoverUnit}` : ''}
              </span>
            </span>
          </div>
          {institutional ? (
            <div data-testid="institutional-net">
              <p className="mb-1.5 text-xs text-secondary-text">
                {marketReviewText.institutional}{breadth.turnoverUnit ? `（${breadth.turnoverUnit}）` : ''}
              </p>
              <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                {([
                  [marketReviewText.foreignNet, institutional.foreignNet],
                  [marketReviewText.trustNet, institutional.trustNet],
                  [marketReviewText.dealerNet, institutional.dealerNet],
                  [marketReviewText.totalNet, institutional.totalNet],
                ] as const).map(([label, value]) => (
                  <div key={label} className="card-inset rounded-lg p-2.5">
                    <p className="text-xs text-secondary-text">{label}</p>
                    <Change value={coerceFiniteNumber(value)} className="mt-0.5 block text-sm font-semibold">
                      {formatSignedAmount(value)}
                    </Change>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </Card>
      ) : null}

      {sectorItems.length > 0 || legacySectorRankings.length > 0 ? (
        <Card variant="surface" padding="md" className="text-left" title={sectorItems.length > 0 ? marketReviewText.sectorBoard : undefined}>
          {sectorItems.length > 0 ? (
            <div data-testid="sector-rank" className="grid grid-cols-1 gap-x-6 gap-y-1 md:grid-cols-2">
              {sectorItems.slice(0, 10).map((item) => (
                <div key={item.name} className="flex items-center justify-between gap-3 text-sm">
                  <span className="min-w-0 truncate text-foreground">{item.name}</span>
                  <Change value={item.changePct} className="shrink-0">{formatPercent(item.changePct)}</Change>
                </div>
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {legacySectorRankings.flatMap((rankings, rankingIndex) => (['top', 'bottom'] as const).map((side) => {
                const rows = rankings?.[side] ?? [];
                if (rows.length === 0) return null;
                return (
                  <div key={`${rankingIndex}-${side}`} className="card-inset rounded-lg p-3">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <p className="text-xs text-secondary-text">
                        {rankings === activeMarket?.sectors ? marketReviewText.industryBoards : marketReviewText.conceptBoards}
                      </p>
                      <span className="text-xs text-secondary-text">
                        {side === 'top' ? marketReviewText.leading : marketReviewText.lagging}
                      </span>
                    </div>
                    <div className="space-y-1.5">
                      {rows.slice(0, 5).map((item, index) => (
                        <div key={`${item.name}-${index}`} className="flex items-center justify-between gap-3 text-sm">
                          <span className="min-w-0 truncate text-foreground">{item.name}</span>
                          <Change value={coerceFiniteNumber(item.changePct)} className="shrink-0">
                            {formatPercent(coerceFiniteNumber(item.changePct))}
                          </Change>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              }))}
            </div>
          )}
        </Card>
      ) : null}

      {isLoading ? (
        <div data-testid="market-review-skeleton" className="space-y-3" aria-busy="true" aria-label={text.loadingReport}>
          {[0, 1, 2].map((key) => (
            <div key={key} className="h-16 animate-pulse rounded-[var(--radius-card)] bg-subtle" />
          ))}
        </div>
      ) : error ? (
        <Card variant="surface" padding="md" className="text-left">
          <div className="flex flex-col items-center justify-center gap-3 py-8">
            <ShieldAlert className="h-6 w-6 text-danger" aria-hidden="true" />
            <p className="text-sm text-danger">{error}</p>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                setLoadError(null);
                setRetryVersion((version) => version + 1);
              }}
            >
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              {marketReviewText.retry}
            </Button>
          </div>
        </Card>
      ) : (
        <div data-testid="market-review-report" className="space-y-2" aria-label={marketReviewText.fullText}>
          {sections.map(({ id, title, content: sectionContent, icon: Icon }) => (
            // 有結構化資料時長文預設收合；只有 Markdown 的舊報告沒有別的內容可看，預設展開。
            <details key={id} open={!hasStructuredView} className="card-surface rounded-[var(--radius-card)] p-4 text-left">
              <summary className="flex cursor-pointer list-none items-center gap-2">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="h-4 w-4" aria-hidden="true" />
                </span>
                <h3 className="text-sm font-semibold text-foreground">{title}</h3>
              </summary>
              <div className="mt-3">
                <ReportMarkdownBody content={sectionContent} className="market-review-markdown" />
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
};
