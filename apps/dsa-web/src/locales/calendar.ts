import type { UiLanguage } from '../i18n/uiText';

const en = {
  title: 'Event calendar',
  description: 'Earnings for your holdings and watchlist, plus important economic dates.',
  month: 'Month',
  previous: 'Previous month',
  next: 'Next month',
  loading: 'Loading calendar',
  loadError: 'The calendar could not be loaded.',
  empty: 'No cached events this month',
  emptyDescription: 'The scheduled refresh collects announced dates. Missing dates remain undetermined.',
  confirmed: 'Confirmed',
  estimated: 'Estimated',
  deadline: 'Statutory deadline',
  deadlineNote: 'A filing deadline is not the company’s actual release date.',
  earnings: 'Earnings',
  investor_conference: 'Investor conference',
  fomc: 'FOMC',
  revenue_deadline: 'Monthly revenue',
  financial_deadline: 'Financial filing',
  macro: 'Economic release',
  eastern: 'US Eastern date (ET)',
  taipei: 'Taipei date',
  timezoneNote: 'US dates use Eastern Time (ET); Taiwan dates use Taipei time. Dates are not converted to your device timezone.',
  source: 'Source',
  undated: 'No date scheduled yet',
  showPast: 'Show past dates',
  hidePast: 'Hide past dates',
  cache: 'Cache updated',
  notRefreshed: 'Awaiting scheduled refresh',
};

export const CALENDAR_TEXT: Record<UiLanguage, typeof en> = {
  en,
  zh: {
    title: '事件日历', description: '持仓与自选股的财报日，以及重要总经日期。', month: '月份', previous: '上个月', next: '下个月',
    loading: '正在加载日历', loadError: '日历暂时无法加载。', empty: '本月暂无已缓存事件', emptyDescription: '后台排程收集已公布日期；没有日期时保持未定。',
    confirmed: '已确认', estimated: '推估', deadline: '法定期限', deadlineNote: '申报期限不是公司实际发布日期。', earnings: '财报', investor_conference: '法说会', fomc: 'FOMC', revenue_deadline: '月营收', financial_deadline: '财报申报', macro: '总经发布',
    showPast: '显示已过去的日期', hidePast: '隐藏已过去的日期', eastern: '美东日期（ET）', taipei: '台北日期', timezoneNote: '美股采用美东日期（ET），台股采用台北日期；不会转换成装置时区。', source: '来源', undated: '尚未排定日期', cache: '缓存更新', notRefreshed: '等待后台排程更新',
  },
  'zh-TW': {
    title: '事件行事曆', description: '持股與自選股的財報日，以及重要總經日期。', month: '月份', previous: '上個月', next: '下個月',
    loading: '正在載入行事曆', loadError: '行事曆暫時無法載入。', empty: '本月暫無已快取事件', emptyDescription: '背景排程收集已公布日期；沒有日期時保持未定。',
    confirmed: '已確認', estimated: '推估', deadline: '法定期限', deadlineNote: '申報期限不是公司實際發布日期。', earnings: '財報', investor_conference: '法說會', fomc: 'FOMC', revenue_deadline: '月營收', financial_deadline: '財報申報', macro: '總經發布',
    showPast: '顯示已過去的日期', hidePast: '隱藏已過去的日期', eastern: '美東日期（ET）', taipei: '台北日期', timezoneNote: '美股採用美東日期（ET），台股採用台北日期；不會轉換成裝置時區。', source: '來源', undated: '尚未排定日期', cache: '快取更新', notRefreshed: '等待背景排程更新',
  },
};
