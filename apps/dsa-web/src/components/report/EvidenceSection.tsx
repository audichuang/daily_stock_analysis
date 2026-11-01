import { ChevronDown } from 'lucide-react';
import type React from 'react';
import type { ReportLanguage } from '../../types/analysis';
import type { ResearchEvidenceItem } from '../../types/researchArtifact';
import { formatNumber } from '../../utils/format';
import { normalizeReportLanguage } from '../../utils/reportLanguage';
import { Badge, Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';

const TEXT = {
  zh: {
    title: '证据', notScored: '未计分', partial: '仅涵盖部分资料', total: '共 {n} 笔', windowDays: '近 {n} 天',
    asOf: '资料日', shortAsOf: '申报结算日（非当日）', open: '开启原文',
    groups: { news: '新闻', fundamental: '基本面', market: '市场结构', short_interest: '放空', sec_filing: 'SEC 公告', insider: '内部人交易', ratings: '评等', estimates: '法人预估', ownership: '持股结构', capital_flow: '资金流' },
    ratings: { up: '上调', down: '下调', main: '维持', reit: '重申', init: '首评', other: '其他' },
    facts: { sharesShort: '放空股数', daysToCover: '回补天数', floatPct: '占流通股 %', items: '项目', acceptedAt: '受理时间', buyShares: '买进股数', sellShares: '卖出股数', netShares: '净股数', count: '笔数', institutionsPct: '法人持股 %', insidersPct: '内部人持股 %', avg: '平均', low: '最低', high: '最高', yearAgo: '去年同期', analysts: '分析师数', upWeek: '近一周上修', upMonth: '近一月上修', downWeek: '近一周下修', downMonth: '近一月下修', eps: 'EPS', revenue: '营收', revisions: '修正家数' },
  },
  en: {
    title: 'Evidence', notScored: 'Not scored', partial: 'Partial coverage', total: '{n} in total', windowDays: 'Last {n} days',
    asOf: 'As of', shortAsOf: 'Settlement date (not today)', open: 'Open source',
    groups: { news: 'News', fundamental: 'Fundamentals', market: 'Market structure', short_interest: 'Short interest', sec_filing: 'SEC filings', insider: 'Insider trades', ratings: 'Ratings', estimates: 'Estimates', ownership: 'Ownership', capital_flow: 'Capital flow' },
    ratings: { up: 'Upgrades', down: 'Downgrades', main: 'Maintained', reit: 'Reiterated', init: 'Initiated', other: 'Other' },
    facts: { sharesShort: 'Shares short', daysToCover: 'Days to cover', floatPct: '% of float', items: 'Items', acceptedAt: 'Accepted', buyShares: 'Shares bought', sellShares: 'Shares sold', netShares: 'Net shares', count: 'Count', institutionsPct: 'Institutions %', insidersPct: 'Insiders %', avg: 'Average', low: 'Low', high: 'High', yearAgo: 'Year ago', analysts: 'Analysts', upWeek: 'Up, 7 days', upMonth: 'Up, 30 days', downWeek: 'Down, 7 days', downMonth: 'Down, 30 days', eps: 'EPS', revenue: 'Revenue', revisions: 'Revisions' },
  },
  'zh-TW': {
    title: '證據', notScored: '未計分', partial: '僅涵蓋部分資料', total: '共 {n} 筆', windowDays: '近 {n} 天',
    asOf: '資料日', shortAsOf: '申報結算日（非當日）', open: '開啟原文',
    groups: { news: '新聞', fundamental: '基本面', market: '市場結構', short_interest: '放空', sec_filing: 'SEC 公告', insider: '內部人交易', ratings: '評等', estimates: '法人預估', ownership: '持股結構', capital_flow: '資金流' },
    ratings: { up: '上調', down: '下調', main: '維持', reit: '重申', init: '首評', other: '其他' },
    facts: { sharesShort: '放空股數', daysToCover: '回補天數', floatPct: '占流通股 %', items: '項目', acceptedAt: '受理時間', buyShares: '買進股數', sellShares: '賣出股數', netShares: '淨股數', count: '筆數', institutionsPct: '法人持股 %', insidersPct: '內部人持股 %', avg: '平均', low: '最低', high: '最高', yearAgo: '去年同期', analysts: '分析師數', upWeek: '近一週上修', upMonth: '近一月上修', downWeek: '近一週下修', downMonth: '近一月下修', eps: 'EPS', revenue: '營收', revisions: '修正家數' },
  },
  ko: {
    title: '근거', notScored: '점수 미반영', partial: '일부 데이터만 포함', total: '총 {n}건', windowDays: '최근 {n}일',
    asOf: '기준일', shortAsOf: '결제 기준일 (당일 아님)', open: '원문 열기',
    groups: { news: '뉴스', fundamental: '펀더멘털', market: '시장 구조', short_interest: '공매도', sec_filing: 'SEC 공시', insider: '내부자 거래', ratings: '투자의견', estimates: '추정치', ownership: '지분 구조', capital_flow: '자금 흐름' },
    ratings: { up: '상향', down: '하향', main: '유지', reit: '재확인', init: '신규', other: '기타' },
    facts: { sharesShort: '공매도 주식 수', daysToCover: '커버 일수', floatPct: '유통주식 대비 %', items: '항목', acceptedAt: '접수 시각', buyShares: '매수 주식 수', sellShares: '매도 주식 수', netShares: '순 주식 수', count: '건수', institutionsPct: '기관 지분 %', insidersPct: '내부자 지분 %', avg: '평균', low: '최저', high: '최고', yearAgo: '전년 동기', analysts: '애널리스트 수', upWeek: '7일 상향', upMonth: '30일 상향', downWeek: '7일 하향', downMonth: '30일 하향', eps: 'EPS', revenue: '매출', revisions: '수정 건수' },
  },
} as const;

type EvidenceText = (typeof TEXT)[keyof typeof TEXT];
type RatingKey = keyof EvidenceText['ratings'];

// 排定畫面順序；context 是輸入資料區塊，放在「資料品質與來源」，這裡不重複。
const GROUP_ORDER = ['sec_filing', 'ratings', 'short_interest', 'insider', 'estimates', 'ownership', 'capital_flow', 'news', 'fundamental', 'market'] as const;

/** 評等動作是 yfinance 的枚舉；其餘歸「其他」，不顯示機器值。 */
const countRatings = (series: Array<Record<string, unknown>>): Array<[RatingKey, number]> => {
  const counts = new Map<RatingKey, number>();
  series.forEach((entry) => {
    const action = String(entry.action ?? '').toLowerCase();
    const key: RatingKey = action === 'up' || action === 'down' || action === 'main' || action === 'reit' || action === 'init' ? action : 'other';
    counts.set(key, (counts.get(key) ?? 0) + 1);
  });
  return [...counts.entries()];
};

const formatFact = (value: unknown): string =>
  typeof value === 'number' ? formatNumber(value) : String(value);

const flattenFacts = (facts: Record<string, unknown>, labels: Record<string, string>): Array<[string, string]> =>
  Object.entries(facts).flatMap(([key, value]): Array<[string, string]> => {
    const label = labels[key];
    if (!label || value === null || value === undefined) return [];
    if (typeof value === 'object') {
      return flattenFacts(value as Record<string, unknown>, labels).map(([inner, reading]) => [`${label} ${inner}`, reading]);
    }
    return [[label, formatFact(value)]];
  });

const EvidenceRow: React.FC<{ item: ResearchEvidenceItem; text: EvidenceText }> = ({ item, text }) => {
  const labels: Record<string, string> = text.facts;
  const facts = flattenFacts(item.facts ?? {}, labels);
  const ratings = item.group === 'ratings' ? countRatings(item.series ?? []) : [];
  // 放空資料是申報結算日的快照，不能讀成今天的放空量。
  const asOfLabel = item.group === 'short_interest' ? text.shortAsOf : text.asOf;
  const asOf = item.observedAt ?? item.asOf;

  return (
    <div data-testid={`evidence-${item.id}`} className="home-subpanel min-w-0 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-foreground">{item.title}</span>
        {item.source ? <span className="text-xs text-muted-text">{item.source}</span> : null}
        {item.countsTowardScore === false ? <Badge variant="default" className="shadow-none">{text.notScored}</Badge> : null}
        {item.complete === false ? <Badge variant="warning" className="shadow-none">{text.partial}</Badge> : null}
      </div>
      <p className="mt-1 flex flex-wrap gap-x-3 text-xs text-secondary-text">
        {asOf ? <span>{asOfLabel} {String(asOf).slice(0, 10)}</span> : null}
        {typeof item.windowDays === 'number' ? <span>{text.windowDays.replace('{n}', String(item.windowDays))}</span> : null}
      </p>
      {item.summary ? <p className="mt-1 whitespace-pre-wrap leading-6 text-secondary-text">{item.summary}</p> : null}
      {ratings.length > 0 ? (
        <p data-testid="evidence-rating-counts" className="mt-1 flex flex-wrap gap-x-3 text-xs tabular-nums text-foreground">
          {ratings.map(([key, count]) => <span key={key}>{text.ratings[key]} {count}</span>)}
        </p>
      ) : null}
      {facts.length > 0 ? (
        <dl className="mt-1 grid grid-cols-2 gap-x-4 gap-y-1 text-xs md:grid-cols-4">
          {facts.map(([label, reading]) => (
            <div key={label} className="min-w-0">
              <dt className="text-muted-text">{label}</dt>
              <dd className="break-words tabular-nums text-foreground">{reading}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {/* 外部來源的摘錄一律當純文字，不經 Markdown 或 HTML 渲染 */}
      {item.excerpt ? (
        <p data-testid="evidence-excerpt" className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded bg-base p-2 text-xs leading-5 text-secondary-text">
          {item.excerpt}
        </p>
      ) : null}
      {item.url ? (
        <a href={item.url} target="_blank" rel="noopener noreferrer" className="home-accent-link mt-1 inline-block text-xs">
          {text.open}
        </a>
      ) : null}
    </div>
  );
};

interface EvidenceSectionProps {
  evidence?: ResearchEvidenceItem[] | null;
  /** 「這份報告缺什麼」一行摘要。 */
  gapSummary?: string | null;
  language?: ReportLanguage;
}

/** 證據依來源分組、預設收合；有資料才顯示。 */
export const EvidenceSection: React.FC<EvidenceSectionProps> = ({ evidence, gapSummary, language = 'zh' }) => {
  const text = TEXT[normalizeReportLanguage(language)];
  const groups = GROUP_ORDER
    .map((group) => ({ group, items: (evidence ?? []).filter((item) => item.group === group) }))
    .filter(({ items }) => items.length > 0);

  if (groups.length === 0 && !gapSummary) {
    return null;
  }

  return (
    <Card variant="surface" padding="md" className="home-panel-card text-left">
      <section data-testid="evidence-section">
        <DashboardPanelHeader title={text.title} className="mb-2" />
        {gapSummary ? <p data-testid="report-gap-summary" className="mb-2 text-xs leading-5 text-secondary-text">{gapSummary}</p> : null}
        <div className="space-y-2">
          {groups.map(({ group, items }) => (
            <details key={group} data-testid={`evidence-group-${group}`} className="group/evidence">
              <summary className="home-surface-button flex cursor-pointer list-none items-center justify-between gap-3 rounded-lg p-2.5 text-sm text-foreground">
                <span>
                  {text.groups[group]}
                  <span className="ml-2 text-xs text-muted-text">{text.total.replace('{n}', String(items.length))}</span>
                </span>
                <ChevronDown className="h-4 w-4 shrink-0 text-muted-text transition-transform group-open/evidence:rotate-180" aria-hidden="true" />
              </summary>
              <div className="mt-2 space-y-2">
                {items.map((item) => <EvidenceRow key={item.id} item={item} text={text} />)}
              </div>
            </details>
          ))}
        </div>
      </section>
    </Card>
  );
};
