// The built-in publish browser presents itself as the desktop Chrome it really is: Electron's default user agent
// adds "<app name>/<version>" and "Electron/<version>" tokens, which some platforms (and Google sign-in) refuse as
// an embedded browser. Only those two tokens are removed - the Chrome version, OS and engine stay the real ones.
export function cleanUserAgent(ua: string, appNames: string[] = []): string {
  let out = ua.replace(/\s+Electron\/\S+/g, '');
  for (const n of appNames) {
    const esc = n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '[ -]?');
    out = out.replace(new RegExp(`\\s+${esc}/\\S+`, 'gi'), '');
  }
  // anything else between "(KHTML, like Gecko)" and "Chrome/" (product names may contain spaces)
  out = out.replace(/(\(KHTML, like Gecko\))[^()]*?(?=\s+Chrome\/)/, '$1');
  return out.replace(/\s{2,}/g, ' ').trim();
}
