import '@testing-library/jest-dom/vitest';

import { cleanup, configure } from '@testing-library/react';
import { afterEach } from 'vitest';

// The pages after sign-in load on their own (D4). A test's first visit to a page waits for the
// test runner to prepare its module, the charts included, so screen queries wait a little longer.
configure({ asyncUtilTimeout: 4000 });

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

// Browser functions jsdom does not have. The application only needs them to exist.
window.matchMedia = (query: string) =>
  ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  }) as MediaQueryList;
window.scrollTo = () => {};
Element.prototype.scrollIntoView = () => {};
