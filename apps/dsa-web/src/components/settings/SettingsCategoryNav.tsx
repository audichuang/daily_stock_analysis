import type React from 'react';
import { Bell, Bot, ChevronRight, Database, Layers3, LineChart, Settings2, SlidersHorizontal } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { getCategoryTitle } from '../../utils/systemConfigI18n';
import { getSettingsCategoryStatus, orderSettingsCategories } from '../../utils/settingsCategoryNav';
import type { SystemConfigCategory, SystemConfigCategorySchema, SystemConfigItem } from '../../types/systemConfig';
import { cn } from '../../utils/cn';

interface SettingsCategoryNavProps {
  categories: SystemConfigCategorySchema[];
  itemsByCategory: Record<string, SystemConfigItem[]>;
  activeCategory: string;
  onSelect: (category: string) => void;
}

const categoryIconMap: Partial<Record<SystemConfigCategory, LucideIcon>> = {
  system: Settings2,
  base: SlidersHorizontal,
  data_source: Database,
  ai_model: Layers3,
  notification: Bell,
  agent: Bot,
  backtest: LineChart,
};

export const SettingsCategoryNav: React.FC<SettingsCategoryNavProps> = ({
  categories,
  itemsByCategory,
  activeCategory,
  onSelect,
}) => {
  const { language, t } = useUiLanguage();

  return (
    <nav
      className="rounded-lg border settings-border bg-card/90 p-2 shadow-soft-card backdrop-blur-sm"
      aria-label={t('settings.categoryNavTitle')}
    >
      <p className="hidden px-2 pb-2 pt-1 text-xs font-semibold text-muted-text lg:block">
        {t('settings.categoryNavTitle')}
      </p>

      <div className="space-y-1">
        {orderSettingsCategories(categories).map((category) => {
          const isActive = category.category === activeCategory;
          const title = getCategoryTitle(category.category, category.title, language);
          const status = getSettingsCategoryStatus(category.category, itemsByCategory[category.category] || [], t);
          const Icon = categoryIconMap[category.category] ?? Layers3;

          return (
            <button
              key={category.category}
              type="button"
              className={cn(
                'flex min-h-11 w-full items-center gap-2 rounded-md border px-3 py-2 text-left transition-[background-color,border-color,box-shadow] duration-200',
                isActive
                  ? 'settings-nav-item-active'
                  : 'border-transparent bg-transparent hover:border-[var(--settings-border)] hover:bg-[var(--settings-surface-hover)]',
              )}
              onClick={() => onSelect(category.category)}
              aria-current={isActive ? 'page' : undefined}
            >
              <Icon
                className={cn('h-4 w-4 shrink-0', isActive ? 'text-[hsl(var(--primary))]' : 'text-muted-text')}
                aria-hidden="true"
              />
              <span className={cn('min-w-0 flex-1 truncate text-sm font-medium', isActive ? 'text-foreground' : 'text-secondary-text')}>
                {title}
              </span>
              <span className="max-w-[45%] shrink-0 truncate text-xs text-muted-text" data-testid={`settings-category-status-${category.category}`}>
                {status}
              </span>
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-text lg:hidden" aria-hidden="true" />
            </button>
          );
        })}
      </div>
    </nav>
  );
};
