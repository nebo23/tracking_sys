import { Link, useRouter, type ErrorComponentProps } from '@tanstack/react-router';
import { FormattedMessage } from 'react-intl';

import { describeError } from '@/api/errors';
import { Logo } from '@/components/Logo';
import { Main, PageMessage } from '@/components/Main';
import { Notice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';

/** Shown while the first answer of a page is on its way. */
export function PendingPage() {
  return (
    <div className="a-center" role="status">
      <span className="c-spinner" aria-hidden="true" />
      <span className="u-sr">
        <FormattedMessage id="common.loading" />
      </span>
    </div>
  );
}

/** Shown when a page could not load what it needs. It says why and offers another try. */
export function ErrorPage({ error }: ErrorComponentProps) {
  const router = useRouter();
  usePageTitle('error.page.title');
  const message = describeError(error);
  return (
    <PageMessage>
      <div className="c-empty">
        <PageHeading className="c-empty__title">
          <FormattedMessage id="error.page.title" />
        </PageHeading>
        <p className="c-empty__text" role="alert">
          <FormattedMessage id={message.id} values={message.values} />
        </p>
        <button type="button" className="c-btn c-btn--primary" onClick={() => void router.invalidate()}>
          <FormattedMessage id="common.retry" />
        </button>
      </div>
    </PageMessage>
  );
}

export function NotFoundPage() {
  usePageTitle('notFound.title');
  return (
    <PageMessage>
      <div className="c-empty">
        <PageHeading className="c-empty__title">
          <FormattedMessage id="notFound.title" />
        </PageHeading>
        <p className="c-empty__text">
          <FormattedMessage id="notFound.text" />
        </p>
        <Link className="c-btn c-btn--primary" to="/">
          <FormattedMessage id="notFound.home" />
        </Link>
      </div>
    </PageMessage>
  );
}

/**
 * The address of a legal text. The texts themselves are not written yet (D-079, D-080): the page
 * says so instead of showing a placeholder that could be mistaken for terms.
 */
export function LegalPage({ title }: { title: 'legal.terms.title' | 'legal.privacy.title' }) {
  usePageTitle(title);
  return (
    <Main className="l-page a-legal">
      <Logo height={28} className="a-auth__logo" />
      <PageHeading>
        <FormattedMessage id={title} />
      </PageHeading>
      <Notice tone="warning">
        <FormattedMessage id="legal.pending" />
      </Notice>
    </Main>
  );
}
