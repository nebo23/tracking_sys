import { ToggleButton, ToggleButtonGroup, type Key } from 'react-aria-components';
import { FormattedMessage, useIntl } from 'react-intl';

import { preferences, usePreferences, type Language, type ThemeChoice } from '@/app/preferences';
import { languageNames, languages } from '@/i18n';
import { cx } from '@/lib/cx';

const item = ({ isSelected }: { isSelected: boolean }) => cx('c-seg__item', isSelected && 'is-active');

const themes: readonly ThemeChoice[] = ['system', 'light', 'dark'];

const isLanguage = (key: Key | undefined): key is Language => languages.some((language) => language === key);
const isTheme = (key: Key | undefined): key is ThemeChoice => themes.some((theme) => theme === key);

/** English or Arabic. Each language is named in itself. */
export function LanguageSwitch() {
  const intl = useIntl();
  const { language } = usePreferences();
  return (
    <ToggleButtonGroup
      className="c-seg"
      aria-label={intl.formatMessage({ id: 'language.label' })}
      selectionMode="single"
      disallowEmptySelection
      selectedKeys={[language]}
      onSelectionChange={(keys) => {
        const [key] = keys;
        if (isLanguage(key)) preferences.setLanguage(key);
      }}
    >
      {languages.map((code) => (
        <ToggleButton key={code} id={code} className={item}>
          <span lang={code}>{languageNames[code]}</span>
        </ToggleButton>
      ))}
    </ToggleButtonGroup>
  );
}

/** The device setting, light or dark. */
export function ThemeSwitch() {
  const intl = useIntl();
  const { theme } = usePreferences();
  return (
    <ToggleButtonGroup
      className="c-seg"
      aria-label={intl.formatMessage({ id: 'theme.label' })}
      selectionMode="single"
      disallowEmptySelection
      selectedKeys={[theme]}
      onSelectionChange={(keys) => {
        const [key] = keys;
        if (isTheme(key)) preferences.setTheme(key);
      }}
    >
      {themes.map((choice) => (
        <ToggleButton key={choice} id={choice} className={item}>
          <FormattedMessage id={`theme.${choice}`} />
        </ToggleButton>
      ))}
    </ToggleButtonGroup>
  );
}
