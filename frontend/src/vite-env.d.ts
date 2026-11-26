/// <reference types="vite/client" />

// The only settings the application reads. Neither is a secret: both are compiled into the bundle.
interface ImportMetaEnv {
  /** Origin of the API, for example http://127.0.0.1:8000. */
  readonly VITE_API_ORIGIN?: string;
  /** "true" shows the Google sign-in button. The API must have Google sign-in enabled as well. */
  readonly VITE_GOOGLE_SIGN_IN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
