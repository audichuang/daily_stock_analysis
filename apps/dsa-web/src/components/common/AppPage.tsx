import type React from 'react';
import { useContext } from 'react';
import { UNSAFE_LocationContext } from 'react-router-dom';
import { cn } from '../../utils/cn';
import { resolveEmbedMode } from '../../utils/embedMode';

function getSessionStorage(): Storage | null {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/**
 * Same answer as useEmbedMode(), but safe outside a Router: page components are rendered
 * bare in several unit tests, where useLocation() would throw.
 */
// eslint-disable-next-line react-refresh/only-export-components -- hook shared with PageHeader
export function useEmbedModeSafe(): boolean {
  const locationContext = useContext(UNSAFE_LocationContext) as { location?: { search?: string } } | null;
  const search = locationContext?.location?.search
    ?? (typeof window !== 'undefined' ? window.location.search : '');
  return resolveEmbedMode(search, getSessionStorage());
}

interface AppPageProps {
  children: React.ReactNode;
  className?: string;
}

export const AppPage: React.FC<AppPageProps> = ({ children, className = '' }) => {
  const embedded = useEmbedModeSafe();
  return (
    <main
      className={cn(
        'mx-auto min-h-full w-full max-w-7xl space-y-5 pb-8',
        // Embedded in iOS: 16px side margin to match native pages; the shell frame adds no padding.
        embedded ? 'px-4 pt-2' : 'px-4 pt-4 md:px-6 lg:px-8',
        className,
      )}
    >
      {children}
    </main>
  );
};
