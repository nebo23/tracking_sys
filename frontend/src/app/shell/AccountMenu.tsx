import { useNavigate } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import { Button, Header, Menu, MenuItem, MenuSection, MenuTrigger, Popover, Separator, type Selection } from 'react-aria-components';
import { FormattedMessage, useIntl } from 'react-intl';

import type { User } from '@/api/session';
import { Icon } from '@/components/Icon';
import { languageNames, languages } from '@/i18n';
import { initials } from '@/lib/initials';

import { preferences, usePreferences, type ThemeChoice } from '../preferences';

import { menuItem } from './menuItem';

const themes: readonly ThemeChoice[] = ['system', 'light', 'dark'];

const only = (keys: Selection) => (keys === 'all' ? undefined : [...keys][0]);

function Choice({ children }: { children: ReactNode }) {
  return ({ isSelected }: { isSelected: boolean }) => (
    <>
      <span className="u-grow">{children}</span>
      {isSelected ? <Icon name="check" size="sm" /> : null}
    </>
  );
}

interface AccountMenuProps {
  user: User;
  onSignOut: () => void;
}

/** The menu behind the avatar: who is signed in, the language, the theme, the account page, sign out. */
export function AccountMenu({ user, onSignOut }: AccountMenuProps) {
  const intl = useIntl();
  const navigate = useNavigate();
  const { language, theme } = usePreferences();

  return (
    <MenuTrigger>
      <Button
        className="c-btn c-btn--ghost c-btn--icon"
        aria-label={intl.formatMessage({ id: 'shell.account.menu' }, { name: user.display_name })}
      >
        <span className="c-avatar" aria-hidden="true">
          {initials(user.display_name)}
        </span>
      </Button>
      <Popover className="c-menu" placement="bottom end">
        <div className="a-menu__who">
          <span className="u-strong u-truncate">{user.display_name}</span>
          <span className="u-tertiary u-truncate u-ltr">{user.email_normalized}</span>
        </div>
        <div className="c-menu__sep" />
        <Menu className="a-menu" aria-label={intl.formatMessage({ id: 'shell.account.menu' }, { name: user.display_name })}>
          <MenuSection
            selectionMode="single"
            disallowEmptySelection
            selectedKeys={[language]}
            onSelectionChange={(keys) => {
              const key = only(keys);
              if (key === 'en' || key === 'ar') preferences.setLanguage(key);
            }}
          >
            <Header className="c-menu__label">
              <FormattedMessage id="language.label" />
            </Header>
            {languages.map((code) => (
              <MenuItem key={code} id={code} className={menuItem} textValue={languageNames[code]}>
                {Choice({ children: <span lang={code}>{languageNames[code]}</span> })}
              </MenuItem>
            ))}
          </MenuSection>
          <Separator className="c-menu__sep" />
          <MenuSection
            selectionMode="single"
            disallowEmptySelection
            selectedKeys={[theme]}
            onSelectionChange={(keys) => {
              const key = only(keys);
              const chosen = themes.find((choice) => choice === key);
              if (chosen) preferences.setTheme(chosen);
            }}
          >
            <Header className="c-menu__label">
              <FormattedMessage id="theme.label" />
            </Header>
            {themes.map((choice) => (
              <MenuItem key={choice} id={choice} className={menuItem} textValue={intl.formatMessage({ id: `theme.${choice}` })}>
                {Choice({ children: <FormattedMessage id={`theme.${choice}`} /> })}
              </MenuItem>
            ))}
          </MenuSection>
          <Separator className="c-menu__sep" />
          <MenuItem id="account" className={menuItem} onAction={() => void navigate({ to: '/account' })}>
            <Icon name="user" size="sm" />
            <FormattedMessage id="shell.nav.account" />
          </MenuItem>
          <MenuItem id="sign-out" className={menuItem} onAction={onSignOut}>
            <Icon name="log-out" size="sm" mirror />
            <FormattedMessage id="shell.signOut" />
          </MenuItem>
        </Menu>
      </Popover>
    </MenuTrigger>
  );
}
