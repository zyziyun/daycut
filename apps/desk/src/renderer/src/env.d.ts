import type { DeskApi } from '../../shared/deskApi';

declare global {
  interface Window {
    desk: DeskApi;
  }
}
export {};
