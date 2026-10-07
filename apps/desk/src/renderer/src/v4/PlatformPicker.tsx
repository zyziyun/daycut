// Platform chips in the shared order (English / global, Chinese, other languages; connected accounts first inside
// each group). YouTube is ONE chip with two formats - long-form (16:9) and Shorts (9:16, <= 3 min) - picked per
// post: the engine keeps them as two targets (youtube / youtube-shorts).
import { GROUPS, orderPlatforms, PLATFORMS, sortPlatforms, type PlatformGroup } from '../../../shared/platforms';
import { t, tk } from '../i18n';
import { platformName } from './Home';
import { PlatformIcon } from './PlatformIcon';

const YT = ['youtube', 'youtube-shorts'] as const;
const CHIP = { height: 26, padding: '0 9px' } as const;

function grouped(connected: string[]): { group: PlatformGroup; ids: string[] }[] {
  const ids = sortPlatforms(
    PLATFORMS.filter((p) => p.id !== 'youtube-shorts').map((p) => p.id),
    (x) => x,
    connected,
  );
  return GROUPS.map((g) => ({ group: g, ids: ids.filter((id) => PLATFORMS.find((p) => p.id === id)?.group === g) })).filter((g) => g.ids.length);
}

type Props =
  | { multi: true; value: string[]; onChange: (v: string[]) => void; connected?: string[]; testId?: string }
  | { multi?: false; value: string; onChange: (v: string) => void; connected?: string[]; testId?: string };

export function PlatformPicker(props: Props) {
  const connected = props.connected ?? [];
  const sel = props.multi ? props.value : [props.value];
  const on = (id: string) => sel.includes(id);
  const set = (next: string[]) => {
    // stored in registry order, never in click order (international first)
    if (props.multi) props.onChange(orderPlatforms(next));
    else if (next.length) props.onChange(next[next.length - 1]);
  };
  const toggle = (id: string) => (props.multi ? set(on(id) ? sel.filter((x) => x !== id) : [...sel, id]) : set([id]));
  const ytOn = YT.some(on);
  const clickYt = () => {
    if (props.multi) set(ytOn ? sel.filter((x) => !(YT as readonly string[]).includes(x)) : [...sel, 'youtube']);
    else if (!ytOn) set(['youtube']);
  };
  return (
    <div className="col" style={{ gap: 6 }} data-testid={props.testId ? `${props.testId}-groups` : undefined}>
      {grouped(connected).map(({ group, ids }) => (
        <div key={group} className="row" style={{ flexWrap: 'wrap', gap: 6 }} data-group={group}>
          <span className="muted small" style={{ minWidth: 64 }}>
            {tk(`pf.group.${group}`)}
          </span>
          {ids.map((p) =>
            p === 'youtube' ? (
              <span key={p} className="row" style={{ gap: 2 }} data-testid="pf-youtube">
                <button className={`chip ${ytOn ? 'on' : ''}`} aria-pressed={ytOn} onClick={clickYt} data-pf="youtube" data-testid={props.testId} style={CHIP}>
                  <PlatformIcon id="youtube" size={14} />
                  {platformName('youtube')}
                </button>
                {YT.map((f) => (
                  <button
                    key={f}
                    className={`chip ${on(f) ? 'on' : ''}`}
                    aria-pressed={on(f)}
                    onClick={() => toggle(f)}
                    data-format={f === 'youtube' ? 'long' : 'shorts'}
                    data-pf-format={f}
                    title={t(f === 'youtube' ? 'pf.yt.longHint' : 'pf.yt.shortsHint')}
                    style={{ ...CHIP, padding: '0 7px', opacity: ytOn ? 1 : 0.6 }}
                  >
                    {t(f === 'youtube' ? 'pf.yt.long' : 'pf.yt.shorts')}
                  </button>
                ))}
              </span>
            ) : (
              <button key={p} className={`chip ${on(p) ? 'on' : ''}`} aria-pressed={on(p)} onClick={() => toggle(p)} data-pf={p} data-testid={props.testId} style={CHIP}>
                <PlatformIcon id={p} size={14} />
                {platformName(p)}
              </button>
            ),
          )}
        </div>
      ))}
    </div>
  );
}
