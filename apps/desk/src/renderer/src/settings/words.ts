// Engine path / Python in words for Settings › Advanced (never a raw path on the page; the full path is the tooltip).
import type { SettingsMsg } from '../../../shared/deskApi';
import { t } from '../i18n';

const base = (p: string) => p.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || p;

/** "/Users/me/Desktop/reelfold" -> "The reelfold folder on your Desktop" */
export function engineWords(p: string | undefined, packaged?: boolean): string {
  if (packaged) return t('s2.engine.builtIn');
  if (!p) return t('s2.engine.notFound');
  const name = base(p);
  if (/^(\/Users\/[^/]+|\/home\/[^/]+|[A-Za-z]:\\Users\\[^\\]+)[\\/]Desktop[\\/][^\\/]+[\\/]?$/.test(p) || /[\\/]Desktop[\\/]/.test(p)) return t('s2.engine.desktop', { name });
  if (/^(\/Users\/[^/]+|\/home\/[^/]+|[A-Za-z]:\\Users\\[^\\]+)[\\/]/.test(p)) return t('s2.engine.home', { name });
  return t('s2.engine.other', { name });
}

export function pythonWords(s: Pick<SettingsMsg, 'python' | 'resolved'>): string {
  const v = /Python ([\d.]+)/.exec(s.resolved?.runtime ?? '')?.[1];
  if (s.resolved?.runtime && s.resolved.runtime !== 'system') return `${t('s2.engine.pyBundled')}${v ? ` · Python ${v}` : ''}`;
  if (s.python) return t('s2.engine.pyCustom', { name: base(s.python) });
  return t('s2.engine.pyAuto');
}

