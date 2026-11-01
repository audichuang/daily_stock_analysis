import type React from 'react';
import { cn } from '../../utils/cn';

interface SkeletonProps {
  className?: string;
}

/** 載入中的佔位方塊；尺寸由 className 決定，對輔助技術隱藏。 */
export const Skeleton: React.FC<SkeletonProps> = ({ className = '' }) => (
  <div aria-hidden="true" data-testid="skeleton" className={cn('animate-pulse rounded bg-elevated', className)} />
);
