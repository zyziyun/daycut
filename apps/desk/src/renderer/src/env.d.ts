import type { DeskApi } from '../../shared/deskApi';

declare global {
  /** apps/desk/package.json version (vite define) */
  const __APP_VERSION__: string;
  interface Window {
    desk: DeskApi;
  }
}
export {};
