import './styles';

import faviconUrl from '@design/brand/favicon.svg';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './app/App';
import { applyPreferences } from './app/preferences';
import { createQueryClient } from './app/queryClient';
import { createAppRouter } from './app/router';
import { watchSession } from './app/sessionLifecycle';
import { captureLinkToken } from './lib/linkToken';

// A token that arrived in a mail link leaves the address bar before anything reads the address.
captureLinkToken();
applyPreferences();

const icon = document.createElement('link');
icon.rel = 'icon';
icon.href = faviconUrl;
document.head.append(icon);

const queryClient = createQueryClient();
const router = createAppRouter(queryClient);

// A 401 outside the sign-in forms may mean the session ended: ask the API, and if so start over.
watchSession(queryClient, router);

const root = document.getElementById('root');
if (!root) throw new Error('The page has no #root element.');

createRoot(root).render(
  <StrictMode>
    <App router={router} queryClient={queryClient} />
  </StrictMode>,
);
