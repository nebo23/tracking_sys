import logoArReversed from '@design/brand/connect-logo-ar-reversed.svg';
import logoAr from '@design/brand/connect-logo-ar.svg';
import logoReversed from '@design/brand/connect-logo-reversed.svg';
import logo from '@design/brand/connect-logo.svg';
import markReversed from '@design/brand/connect-mark-reversed.svg';
import mark from '@design/brand/connect-mark.svg';
import { useIntl } from 'react-intl';

import { usePreferences, useResolvedTheme } from '@/app/preferences';

interface LogoProps {
  /** The wordmark in the language of the page, or the magnet alone. */
  variant?: 'wordmark' | 'mark';
  /** "reversed" is for the dark brand surface, whatever the theme. */
  tone?: 'auto' | 'reversed';
  height?: number;
  className?: string;
}

export function Logo({ variant = 'wordmark', tone = 'auto', height = 24, className }: LogoProps) {
  const intl = useIntl();
  const { language } = usePreferences();
  const theme = useResolvedTheme();
  const reversed = tone === 'reversed' || theme === 'dark';
  let source: string;
  if (variant === 'mark') source = reversed ? markReversed : mark;
  else if (language === 'ar') source = reversed ? logoArReversed : logoAr;
  else source = reversed ? logoReversed : logo;
  return <img src={source} alt={intl.formatMessage({ id: 'app.name' })} height={height} className={className} />;
}
