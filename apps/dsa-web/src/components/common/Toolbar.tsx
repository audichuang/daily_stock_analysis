import React, { useState } from 'react';
import { SlidersHorizontal } from 'lucide-react';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { cn } from '../../utils/cn';
import { Button } from './Button';
import { Drawer } from './Drawer';

interface FilterBarProps {
  /** 主要條件，兩種尺寸都直接顯示。 */
  primary?: React.ReactNode;
  /** 次要條件：桌機直接顯示，手機收進 Drawer。 */
  secondary?: React.ReactNode;
  /** 右側動作。 */
  actions?: React.ReactNode;
  /** 已套用的次要條件數，顯示在手機的篩選按鈕上。 */
  activeCount?: number;
  className?: string;
}

export const FilterBar: React.FC<FilterBarProps> = ({ primary, secondary, actions, activeCount = 0, className = '' }) => {
  const { t } = useUiLanguage();
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className={cn('flex flex-wrap items-center justify-between gap-2', className)}>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        {primary}
        {secondary ? (
          <>
            <div data-testid="filter-bar-secondary-inline" className="hidden flex-wrap items-center gap-2 md:flex">
              {secondary}
            </div>
            <Button
              variant="secondary"
              data-testid="filter-bar-more"
              className="md:hidden"
              onClick={() => setDrawerOpen(true)}
            >
              <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
              {t('common.filters')}
              {activeCount > 0 ? <span className="tabular-nums text-cyan">{activeCount}</span> : null}
            </Button>
          </>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      {secondary ? (
        <Drawer isOpen={drawerOpen} onClose={() => setDrawerOpen(false)} title={t('common.filters')}>
          <div className="flex flex-col gap-3">{secondary}</div>
        </Drawer>
      ) : null}
    </div>
  );
};
