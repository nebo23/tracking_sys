import type { ReactNode } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { Icon } from '@/components/Icon';
import { Logo } from '@/components/Logo';
import { Main } from '@/components/Main';
import { LanguageSwitch } from '@/components/PreferenceSwitches';
import { PullPicture } from '@/components/PullPicture';

/**
 * The frame of the screens a person sees before the workspace: the brand side with the moving
 * picture, the language switch in the top corner and the form (D-075).
 */
export function AuthLayout({ children }: { children: ReactNode }) {
  const intl = useIntl();
  return (
    <div className="l-auth">
      <section className="l-auth__brand" aria-label={intl.formatMessage({ id: 'auth.brand.label' })}>
        <Logo tone="reversed" height={32} className="a-auth__logo" />
        <div className="l-stack l-stack--loose">
          <PullPicture label={intl.formatMessage({ id: 'auth.brand.picture' })} />
          <p className="l-auth__statement">
            <FormattedMessage id="auth.brand.statement" />
          </p>
          <ul className="l-auth__points">
            <li>
              <Icon name="check" size="sm" />
              <FormattedMessage id="auth.brand.point1" />
            </li>
            <li>
              <Icon name="check" size="sm" />
              <FormattedMessage id="auth.brand.point2" />
            </li>
          </ul>
        </div>
        <div className="l-spread">
          <p className="l-auth__note">
            <FormattedMessage id="auth.brand.note" />
          </p>
          <label className="l-auth__motion">
            <input type="checkbox" />
            <Icon name="circle-pause" size="sm" />
            <Icon name="play" size="sm" />
            <span className="u-sr">
              <FormattedMessage id="auth.brand.pause" />
            </span>
          </label>
        </div>
      </section>

      <div className="l-auth__lang">
        <LanguageSwitch />
      </div>

      <Main className="l-auth__form">{children}</Main>
    </div>
  );
}
