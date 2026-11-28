import { useRouter } from '@tanstack/react-router';
import { Button, Menu, MenuItem, MenuTrigger, Popover } from 'react-aria-components';
import { FormattedMessage, useIntl } from 'react-intl';

import { Icon } from '@/components/Icon';

import { menuItem } from './menuItem';
import type { Destination } from './navigation';

/**
 * The last place of the phone tab bar inside a client (D5 of the completion entry review): it
 * opens the rest of the client's menu, and reads as the current place when one of them is open.
 */
export function MoreTab({ destinations, pathname }: { destinations: readonly Destination[]; pathname: string }) {
  const intl = useIntl();
  const router = useRouter();
  const hrefOf = (destination: Destination) => router.buildLocation(destination.link as never).pathname;
  const here = destinations.some((destination) => {
    const address = hrefOf(destination);
    return pathname === address || pathname.startsWith(`${address}/`);
  });
  return (
    <MenuTrigger>
      <Button className={here ? 'c-tabbar__item is-active' : 'c-tabbar__item'}>
        <Icon name="ellipsis" size="md" />
        <FormattedMessage id="shell.nav.more" />
      </Button>
      <Popover className="c-menu" placement="top end">
        <Menu className="a-menu" aria-label={intl.formatMessage({ id: 'shell.nav.more' })}>
          {destinations.map((destination) => (
            <MenuItem
              key={destination.key}
              id={destination.key}
              className={menuItem}
              textValue={intl.formatMessage({ id: destination.label })}
              onAction={() => void router.navigate(destination.link as never)}
            >
              <Icon name={destination.icon} size="sm" />
              <span className="u-grow">
                <FormattedMessage id={destination.label} />
              </span>
            </MenuItem>
          ))}
        </Menu>
      </Popover>
    </MenuTrigger>
  );
}
