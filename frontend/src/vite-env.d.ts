/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Hosted build only: backend health URL requested directly to wake a sleeping free-tier instance. */
  readonly VITE_WAKE_URL?: string;
}
