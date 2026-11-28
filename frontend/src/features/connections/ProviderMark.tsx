import { useIntl } from 'react-intl';

import { Icon } from '@/components/Icon';
import { cx } from '@/lib/cx';

import { providerLabel } from './providers';

/** The name of a provider in the language of the interface, or the API's own word for an unknown one. */
export function useProviderName(): (id: string) => string {
  const intl = useIntl();
  return (id) => {
    const { name } = providerLabel(id);
    return name ? intl.formatMessage({ id: name }) : id;
  };
}

interface ProviderMarkProps {
  provider: string;
  /** Larger, for the head of a connection card. */
  large?: boolean;
  /** Names the provider for assistive technology. Leave out when its name stands beside the mark. */
  labelled?: boolean;
}

/** The provider's own mark, never mirrored. A provider without a mark gets a plain plug. */
export function ProviderMark({ provider, large = false, labelled = false }: ProviderMarkProps) {
  const name = useProviderName()(provider);
  const { glyph } = providerLabel(provider);
  const label = labelled ? { role: 'img', 'aria-label': name } : { 'aria-hidden': true };
  if (!glyph) {
    return (
      <span {...label}>
        <Icon name="plug" size={large ? 'md' : undefined} />
      </span>
    );
  }
  return <span className={cx('c-glyph', `c-glyph--${glyph}`, large && 'c-icon--md')} {...label} />;
}
