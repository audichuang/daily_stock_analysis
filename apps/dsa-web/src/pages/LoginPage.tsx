import type React from 'react';
import { useState, useEffect } from 'react';
import { Loader2 } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Button, Input } from '../components/common';
import { UiLanguageToggle } from '../components/i18n/UiLanguageToggle';
import type { ParsedApiError } from '../api/error';
import { isParsedApiError } from '../api/error';
import { useAuth } from '../hooks';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type { UiTextKey } from '../i18n/uiText';
import { resolveLoginRedirect } from '../utils/loginRedirect';

/** 密碼錯與連不上要講不同的話；其他後端回覆（例如設定密碼的格式檢查）沿用原文。 */
function resolveLoginErrorKey(error: ParsedApiError): UiTextKey | null {
  if (error.status === 401) {
    return 'login.wrongPassword';
  }
  if (error.status === 429) {
    return 'login.rateLimited';
  }
  if (
    error.status === undefined
    || error.status >= 500
    || error.category === 'local_connection_failed'
    || error.category === 'upstream_network'
    || error.category === 'upstream_timeout'
  ) {
    return 'login.connectionError';
  }
  return null;
}

const LoginPage: React.FC = () => {
  const { login, passwordSet, setupState } = useAuth();
  const { t } = useUiLanguage();
  const navigate = useNavigate();

  useEffect(() => {
    document.title = t('login.pageTitle');
  }, [t]);
  const [searchParams] = useSearchParams();
  const redirect = resolveLoginRedirect(searchParams.get('redirect'));

  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | ParsedApiError | null>(null);

  const isFirstTime = setupState === 'no_password' || !passwordSet;
  const canSubmit = password.length > 0 && (!isFirstTime || passwordConfirm.length > 0) && !isSubmitting;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) {
      return;
    }
    setError(null);
    if (isFirstTime && password !== passwordConfirm) {
      setError(t('login.passwordMismatch'));
      return;
    }
    setIsSubmitting(true);
    try {
      const result = await login(password, isFirstTime ? passwordConfirm : undefined);
      if (result.success) {
        navigate(redirect, { replace: true });
      } else {
        setError(result.error ?? t('login.loginFailed'));
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  let errorText = '';
  if (isParsedApiError(error)) {
    const key = resolveLoginErrorKey(error);
    errorText = key ? t(key) : error.message;
  } else if (error) {
    errorText = error;
  }

  return (
    <div className="relative flex min-h-[100dvh] items-center justify-center bg-[var(--login-bg-main)] px-4 py-8 font-sans">
      <div className="absolute right-4 top-[calc(1rem+env(safe-area-inset-top,0px))] z-10">
        <UiLanguageToggle />
      </div>

      <div
        data-testid="login-card"
        className="w-full max-w-[400px] rounded-2xl border border-[var(--login-border-card)] bg-[var(--login-bg-card)] p-6 shadow-soft-card sm:p-8"
      >
        <p className="mb-6 text-lg font-bold text-[var(--login-text-primary)]">DSA</p>
        <h1 className="text-2xl font-bold text-[var(--login-text-primary)]">
          {isFirstTime ? t('login.setupTitle') : t('login.adminLogin')}
        </h1>
        <p className="mb-6 mt-2 text-sm text-[var(--login-text-secondary)]">
          {isFirstTime ? t('login.setupDescription') : t('login.loginDescription')}
        </p>

        <form onSubmit={handleSubmit}>
          <div className="space-y-4">
            <Input
              id="password"
              type="password"
              appearance="login"
              allowTogglePassword
              iconType="password"
              label={isFirstTime ? t('login.adminPassword') : t('login.loginPassword')}
              placeholder={isFirstTime ? t('login.setupPasswordPlaceholder') : t('login.loginPasswordPlaceholder')}
              hint={isFirstTime ? t('login.passwordRule') : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isSubmitting}
              autoFocus
              autoComplete={isFirstTime ? 'new-password' : 'current-password'}
            />

            {isFirstTime ? (
              <Input
                id="passwordConfirm"
                type="password"
                appearance="login"
                allowTogglePassword
                iconType="password"
                label={t('login.confirmPassword')}
                placeholder={t('login.confirmPasswordPlaceholder')}
                value={passwordConfirm}
                onChange={(e) => setPasswordConfirm(e.target.value)}
                disabled={isSubmitting}
                autoComplete="new-password"
              />
            ) : null}
          </div>

          {/* 常駐且預留兩行高度：錯誤出現時版面不跳，輔助工具也會朗讀內容變化。 */}
          <div
            role="alert"
            data-testid="login-error"
            className="mb-2 mt-3 min-h-[2.5rem] text-sm leading-5 text-[var(--login-error-text)]"
          >
            {errorText}
          </div>

          <Button type="submit" variant="primary" size="lg" className="h-12 w-full" disabled={!canSubmit}>
            {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
            <span>
              {isSubmitting
                ? (isFirstTime ? t('login.setupSubmitting') : t('login.loginSubmitting'))
                : (isFirstTime ? t('login.setupSubmit') : t('login.loginSubmit'))}
            </span>
          </Button>
        </form>
      </div>
    </div>
  );
};

export default LoginPage;
