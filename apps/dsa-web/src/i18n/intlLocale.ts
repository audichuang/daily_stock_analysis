import type { UiLanguage } from './uiText';

/** Maps UiLanguage to BCP 47 locale tag for Intl / toLocaleString. */
export const getIntlLocale = (l: UiLanguage): string =>
  l === 'en' ? 'en-US' : l === 'zh-TW' ? 'zh-TW' : 'zh-CN';
