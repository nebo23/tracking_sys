// Build-time settings. See .env.example; nothing here is secret.
export const apiOrigin = (import.meta.env.VITE_API_ORIGIN ?? 'http://127.0.0.1:8000').replace(/\/+$/, '');
export const googleSignInEnabled = import.meta.env.VITE_GOOGLE_SIGN_IN === 'true';
// Development and the browser journeys only: lists the stand-in providers, which contact nobody.
export const syntheticProvidersEnabled = import.meta.env.VITE_SYNTHETIC_PROVIDERS === 'true';
