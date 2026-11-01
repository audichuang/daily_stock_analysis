import type React from 'react';
import { useEffect } from 'react';
import { Home } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../components/common/Button';
import { useUiLanguage } from '../contexts/UiLanguageContext';

const NotFoundPage: React.FC = () => {
  const navigate = useNavigate();
  const { t } = useUiLanguage();

  useEffect(() => {
    document.title = t('notFound.pageTitle');
  }, [t]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center px-4 text-center">
      <p className="mb-6 text-6xl font-bold tabular-nums text-muted-text">404</p>
      <h1 className="mb-2 text-2xl font-bold text-foreground">{t('notFound.title')}</h1>
      <p className="mb-8 text-muted-text">{t('notFound.description')}</p>
      <Button type="button" variant="primary" onClick={() => navigate('/')}>
        <Home className="h-4 w-4" aria-hidden="true" />
        {t('notFound.backHome')}
      </Button>
    </div>
  );
};

export default NotFoundPage;
