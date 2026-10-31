import type React from 'react';
import { Metric } from './Metric';

interface StatCardProps {
  /** Metric label, such as "Total Return". */
  label: string;
  /** Metric value, including numbers or percentages. */
  value: React.ReactNode;
  /** Supporting text, such as "Up 5% vs last month". */
  hint?: React.ReactNode;
  /** Optional trailing icon. */
  icon?: React.ReactNode;
  /** Tone variant that affects the border color. */
  tone?: 'default' | 'primary' | 'success' | 'warning' | 'danger';
  /** Optional extra className. */
  className?: string;
}

/** 轉接 Metric 的相容入口，新程式碼直接用 Metric／MetricGroup。 */
export const StatCard: React.FC<StatCardProps> = (props) => <Metric {...props} />;
