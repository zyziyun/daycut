// Opt-in anonymous usage counts: the renderer only reports "a batch finished / clips exported / a publish package
// was made" with small integers. Main (main/usage.ts) drops the call unless she turned sharing on; never throws.
import type { UsageNumbersMsg } from '../../../shared/deskApi';

export function trackUsage(ev: 'batch_done' | 'export_done' | 'publish_package', n?: UsageNumbersMsg) {
  try {
    void window.desk.usage?.track(ev, n)?.catch(() => undefined);
  } catch {
    /* preload without usage (old test stubs) */
  }
}
