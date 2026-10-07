// Publish: package -> confirm the exact list (hash = confirmation code) -> per-platform built-in browser with
// the creator's own login -> assisted fill of one confirmed item -> she reviews and presses publish herself ->
// "mark posted" (optional URL) is logged.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { FillResult, FillStepMsg, PostedEntryMsg, PublishStateMsg } from '../../../shared/deskApi';
import { adapterFor, type Adapter } from '../../../shared/publish/adapterSchema';
import { checkCopy, type CopyCheck, type PostCopy } from '../../../shared/publish/postCopy';
import { platformInfo } from '../../../shared/platforms';
import { PlatformIcon } from '../v4/PlatformIcon';
import type { Confirmation } from '../../../shared/publish/gating';
import type { ManifestItem } from '../../../shared/types';
import { ErrorBox, Field, Modal } from '../components/ui';
import { getLang, t, tk } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { useHistory } from '../lib/history';
import { href } from '../lib/router';
import type { PackageCheck } from '../../../shared/types';
import { basePlatform } from '../../../shared/publish/adapterSchema';
import { SCHEDULE_PLATFORMS } from '../v4/PlatformIcon';
import { PlatformPicker } from '../v4/PlatformPicker';
import { sortAdapters, useConnectedPlatforms } from '../v4/Channels';

const itemKey = (i: { job: string; platform: string }) => `${i.job}|${i.platform}`;

export function Publish({ batch }: { batch: string }) {
  const { client } = useEngine();
  const man = useLoad((c) => c.manifest(batch), [batch]);
  const [adapters, setAdapters] = useState<Adapter[]>([]);
  const [adapterErrors, setAdapterErrors] = useState<{ file: string; error: string }[]>([]);
  const [accounts, setAccounts] = useState<Record<string, string[]>>({});
  const [confs, setConfs] = useState<Confirmation[]>([]);
  const [posted, setPosted] = useState<PostedEntryMsg[]>([]);
  const [adapterId, setAdapterId] = useState<string>('');
  const [account, setAccount] = useState<string>('');
  const [sel, setSel] = useState<string>('');
  const [bstate, setBstate] = useState<PublishStateMsg | null>(null);
  const [steps, setSteps] = useState<FillStepMsg[]>([]);
  const [fill, setFill] = useState<FillResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null); // success notes (not errors)
  const [modal, setModal] = useState<null | 'confirm' | 'account' | 'posted'>(null);
  const [perDay, setPerDay] = useState(1);
  const [start, setStart] = useState('');
  const [times, setTimes] = useState('12:00,19:00');
  const [copy, setCopy] = useState<PostCopy | null>(null);
  const [params, setParams] = useState<Record<string, string>>({});

  const { data: hist } = useHistory();
  const entry = hist?.items.find((i) => i.id === batch);
  // a work folder / project (not a batch): the package is made here from chosen clips x platforms (workpkg.py)
  const isWork = !!entry && (entry.kind === 'work' || entry.kind === 'project') && !entry.openable;
  const [repack, setRepack] = useState(false);
  const m = man.data?.manifest ?? null;
  const verify = man.data?.verify;
  const adapter = adapters.find((a) => a.id === adapterId) ?? null;
  const confirmed = !!m && !!verify?.ok && confs.some((c) => c.code === m.confirmation_code);
  const items = useMemo(() => (m && adapter ? m.items.filter((i) => adapterFor(i.platform, [adapter])) : []), [m, adapter]);
  const item = items.find((i) => itemKey(i) === sel) ?? null;
  useEffect(() => {
    setCopy(null);
    if (!item) return;
    let live = true;
    void window.desk.publish
      .caption(batch, item.job, item.platform)
      .then((c) => live && setCopy({ title: c.title, description: c.description, tags: c.tags }))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [batch, item]);
  const rules = item ? platformInfo(basePlatform(item.platform))?.copy : undefined;
  const checks: CopyCheck[] = adapter && copy ? checkCopy(adapter.fields, copy, rules ? { titleRequired: rules.titleRequired, links: rules.links, noHashtags: rules.hashtags.max === 0 } : {}) : [];
  const postedKeys = new Set(posted.filter((p) => m && p.code === m.confirmation_code).map((p) => itemKey(p)));

  const refreshLocal = useCallback(async () => {
    const [a, acc, c, p] = await Promise.all([window.desk.publish.adapters(), window.desk.publish.accounts(), window.desk.publish.confirmations(batch), window.desk.publish.postedLog(batch)]);
    const chans = await window.desk.publish.channels().catch(() => []);
    // the shared platform order (English / global, Chinese, other); connected accounts first inside each group
    const sorted = sortAdapters(a.adapters, chans);
    setAdapters(sorted);
    setAdapterErrors(a.errors);
    setAccounts(acc);
    setConfs(c);
    setPosted(p);
    setAdapterId((cur) => cur || sorted.find((x) => (acc[x.id] ?? []).length)?.id || sorted[0]?.id || '');
  }, [batch]);

  useEffect(() => {
    void refreshLocal();
    const off1 = window.desk.on('publish:state', (s) => setBstate(s as PublishStateMsg));
    const off2 = window.desk.on('publish:fillStep', (s) => setSteps((x) => [...x, s as FillStepMsg]));
    return () => {
      off1();
      off2();
      void window.desk.publish.hide();
    };
  }, [refreshLocal]);

  useEffect(() => {
    const list = accounts[adapterId] ?? [];
    setAccount((cur) => (list.includes(cur) ? cur : list[0] ?? ''));
    setFill(null);
    setSteps([]);
  }, [adapterId, accounts]);

  // ------------------------------------------------ embedded browser placement
  const slot = useRef<HTMLDivElement>(null);
  const overlay = modal !== null;
  const browserOpen = !!bstate && bstate.adapterId === adapterId && bstate.account === account;
  useLayoutEffect(() => {
    const el = slot.current;
    if (!el) return;
    const send = () => {
      const r = el.getBoundingClientRect();
      const show = browserOpen && !overlay;
      void window.desk.publish.setBounds(show ? { x: Math.round(r.left), y: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) } : { x: 0, y: 0, width: 0, height: 0 });
    };
    send();
    const ro = new ResizeObserver(send);
    ro.observe(el);
    window.addEventListener('resize', send);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', send);
    };
  }, [browserOpen, overlay]);

  async function guard(fn: () => Promise<unknown>) {
    setMsg(null);
    setInfo(null);
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setMsg((e as Error).message.replace(/^Error invoking remote method '[^']+': (Error: )?/, ''));
    } finally {
      setBusy(false);
    }
  }

  const open = (page: 'upload' | 'login') => guard(() => window.desk.publish.open(adapterId, account, page));

  const doFill = () =>
    guard(async () => {
      if (!m || !item) return;
      setSteps([]);
      setFill(null);
      const typed = Object.fromEntries((adapter?.params ?? []).map((p) => [p.key, (params[p.key] ?? '').trim()]).filter(([, v]) => v));
      const r = await window.desk.publish.fill({ batchId: batch, code: m.confirmation_code, job: item.job, platform: item.platform, adapterId, account, ...(Object.keys(typed).length ? { params: typed } : {}) });
      setFill(r);
    });

  const lang = getLang();

  return (
    <>
      <div className="topbar">
        <h1>{t('pub.title')}</h1>
        {m && <span className="badge mono">{m.confirmation_code}</span>}
        {m && (confirmed ? <span className="badge accent">{t('pub.listConfirmed')}</span> : <span className="badge danger">{t('pub.notConfirmed')}</span>)}
        <div className="sp" />
      </div>
      <div className="page">
        <div className="pub">
          <div className="left">
            <ErrorBox error={man.error ?? msg} />
            {info && (
              <div className="notice accent small" data-testid="pub-info">
                {info}
              </div>
            )}
            {adapterErrors.map((e) => (
              <div key={e.file} className="err small">
                {t('pub.adapterError')}: {e.file}: {e.error}
              </div>
            ))}
            {isWork && (!m || repack) && man.data && (
              <WorkPackageCard
                batch={batch}
                busy={busy}
                onDone={() => {
                  setRepack(false);
                  setSel('');
                  man.reload();
                }}
                guard={guard}
              />
            )}
            {isWork && m && !repack && (
              <div className="row small">
                <button className="btn ghost sm" onClick={() => setRepack(true)} data-testid="pkg-redo">
                  {t('pkg.redo')}
                </button>
                <a className="btn ghost sm" href={href({ name: 'channels' })}>
                  {t('ch.manage')}
                </a>
              </div>
            )}
            {!isWork && !m && man.data && (
              <div className="card col">
                <b>{t('pub.packageFirst')}</b>
                <span className="muted small">{t('pub.packageHint')}</span>
                <div className="row">
                  <Field label={t('pub.perDay')}>
                    <input className="input" type="number" min={1} max={20} value={perDay} onChange={(e) => setPerDay(Math.max(1, Number(e.target.value) || 1))} style={{ width: 70 }} />
                  </Field>
                  <Field label={t('pub.start')}>
                    <input className="input" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
                  </Field>
                </div>
                <Field label={t('pub.times')}>
                  <input className="input" value={times} onChange={(e) => setTimes(e.target.value)} />
                </Field>
                <button
                  className="btn primary"
                  disabled={busy}
                  onClick={() =>
                    guard(async () => {
                      await client!.package(batch, { per_day: perDay, start: start || undefined, times: times.split(',').map((x) => x.trim()).filter(Boolean) });
                      man.reload();
                    })
                  }
                >
                  {t('pub.package')}
                </button>
              </div>
            )}
            {m && !verify?.ok && <div className="notice">{t('pub.manifestChanged')}</div>}
            {m && verify?.ok && !confirmed && (
              <div className="notice">
                {t('pub.confirmNeeded', { n: m.items.length, code: m.confirmation_code })}
                <div style={{ marginTop: 6 }}>
                  <button className="btn primary sm" onClick={() => setModal('confirm')} data-testid="pub-review-list">
                    {t('pub.reviewList')}
                  </button>
                </div>
              </div>
            )}
            <div className="tabs">
              {adapters.map((a) => (
                <button key={a.id} className={`tab ${a.id === adapterId ? 'on' : ''}`} onClick={() => setAdapterId(a.id)} data-adapter={a.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <PlatformIcon id={a.packagePlatforms[0]} size={14} title={a.name} />
                  {lang === 'zh-CN' ? a.nameZh : a.name}
                  {a.status !== 'verified' && <span className="muted"> · {t(`adapter.${a.status}`)}</span>}
                </button>
              ))}
            </div>
            {adapter && (
              <>
                <div className="notice accent small">
                  <b>{t('pub.disclosure')}</b> {lang === 'zh-CN' ? adapter.disclosure.zh : adapter.disclosure.en}
                </div>
                {adapter.guide && (
                  <div className="notice small" data-testid="pub-guide">
                    <b>{t('pub.guide')}</b> {lang === 'zh-CN' ? adapter.guide.zh : adapter.guide.en}
                  </div>
                )}
                {adapter.herChoices && (
                  <div className="muted small" data-testid="pub-her-choices">
                    <b>{t('pub.herChoices')}:</b> {(lang === 'zh-CN' ? adapter.herChoices.zh : adapter.herChoices.en).join(' · ')}
                  </div>
                )}
                {adapter.status === 'todo' && <div className="notice small">{t('pub.adapterTodo')}</div>}
                {adapter.status === 'unverified' && <div className="muted small">{t('pub.adapterUnverified')}</div>}
                <div className="row">
                  <select className="input" style={{ flex: 1 }} value={account} onChange={(e) => setAccount(e.target.value)}>
                    {(accounts[adapterId] ?? []).length === 0 && <option value="">{t('pub.noAccount')}</option>}
                    {(accounts[adapterId] ?? []).map((a) => (
                      <option key={a} value={a}>
                        {a}
                      </option>
                    ))}
                  </select>
                  <button className="btn sm" onClick={() => setModal('account')}>
                    {t('pub.addAccount')}
                  </button>
                </div>
                <div className="row">
                  <button className="btn sm" disabled={!account || busy} onClick={() => open('upload')}>
                    {t('pub.openUpload')}
                  </button>
                  <button className="btn sm" disabled={!account || busy} onClick={() => open('login')}>
                    {t('pub.openLogin')}
                  </button>
                </div>
                <div className="muted small">{t('pub.loginNote')}</div>
                {(adapter.params ?? []).map((p) => (
                  <Field key={p.key} label={lang === 'zh-CN' ? p.label.zh : p.label.en}>
                    <input
                      className="input"
                      value={params[p.key] ?? ''}
                      onChange={(e) => setParams((x) => ({ ...x, [p.key]: e.target.value }))}
                      placeholder={p.key === 'subreddit' ? 'r/…' : undefined}
                      data-testid={`pub-param-${p.key}`}
                      spellCheck={false}
                    />
                    <span className="muted small">{p.key === 'subreddit' ? t('pub.subredditHint') : null}</span>
                  </Field>
                ))}
              </>
            )}
            {m && adapter && (
              <div className="col" style={{ gap: 6 }}>
                <b className="small">{t('pub.items', { n: items.length })}</b>
                {items.length === 0 && <span className="muted small">{t('pub.noItems')}</span>}
                {items.map((i) => (
                  <ItemRow key={itemKey(i)} i={i} on={itemKey(i) === sel} posted={postedKeys.has(itemKey(i))} onClick={() => (setSel(itemKey(i)), setFill(null), setSteps([]))} />
                ))}
              </div>
            )}
            {item && adapter && (
              <div className="card col">
                <div className="row" style={{ flexWrap: 'wrap' }}>
                  <button className="btn primary" disabled={!confirmed || adapter.status === 'todo' || !account || busy} onClick={doFill} title={!confirmed ? t('pub.confirmFirst') : undefined}>
                    {busy ? t('common.working') : t('pub.fill')}
                  </button>
                  <button
                    className="btn sm"
                    onClick={() =>
                      guard(async () => {
                        const c = await window.desk.publish.caption(batch, item.job, item.platform);
                        await window.desk.copyText([c.title, c.description, c.tags.map((x) => `#${x}`).join(' ')].filter(Boolean).join('\n\n'));
                        setInfo(t('pub.copied'));
                      })
                    }
                  >
                    {t('pub.copyCaption')}
                  </button>
                  <button
                    className="btn sm"
                    onClick={() =>
                      guard(async () => {
                        const c = await window.desk.publish.caption(batch, item.job, item.platform);
                        if (c.video) await window.desk.showItem(c.video);
                      })
                    }
                  >
                    {t('pub.showFile')}
                  </button>
                </div>
                {item.checks && item.checks.length > 0 && (
                  <div className="col small" data-testid="pkg-item-checks">
                    {item.checks.map((c, k) => (
                      <span key={k} className={c.code === 'ai-label' ? 'warnc' : c.hard ? 'err' : 'muted'} data-code={c.code}>
                        · {checkText(c)}
                      </span>
                    ))}
                  </div>
                )}
                {copy && (
                  <div className="col small" data-testid="pub-checks">
                    <b>{t('pub.checks')}</b>
                    {checks.length === 0 && <span className="okc">{t('pub.check.ok')}</span>}
                    {checks.map((c, k) => (
                      <span key={k} className={c.hard ? 'err' : 'muted'} data-code={c.code}>
                        {c.code !== 'hashtags-over' && c.code !== 'text-over'
                          ? tk(`pkg.c.${c.code}`)
                          : c.code === 'hashtags-over'
                          ? t(c.hard ? 'pub.check.hashtags-hard' : 'pub.check.hashtags-over', { n: c.n, max: c.max, platform: adapter.name })
                          : adapter.fields.description?.count === 'x-weighted' && c.field === 'description'
                            ? t('pub.check.text-over-x', { n: c.n, max: c.max })
                            : t('pub.check.text-over', { field: tk(`fill.${c.field}`), n: c.n, max: c.max })}
                      </span>
                    ))}
                  </div>
                )}
                {steps.length > 0 && (
                  <table className="t small">
                    <tbody>
                      {steps.map((s, k) => (
                        <tr key={k}>
                          <td>{tk(`fill.${s.field}`)}</td>
                          <td className={s.status === 'ok' ? 'okc' : 'err'}>{t(`fill.s.${s.status}`)}</td>
                          <td className="muted mono">{s.detail}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {fill && !fill.ok && (
                  <div className="err small">
                    {tk(`gate.${fill.reason}`)}
                    {fill.detail ? ` (${fill.detail})` : ''}
                  </div>
                )}
                {fill?.ok && <div className="notice accent small">{t('pub.afterFill')}</div>}
                <button className="btn" disabled={!confirmed || postedKeys.has(itemKey(item))} onClick={() => setModal('posted')} data-testid="pub-mark-posted">
                  {postedKeys.has(itemKey(item)) ? t('pub.alreadyPosted') : t('pub.markPosted')}
                </button>
              </div>
            )}
            {posted.length > 0 && (
              <div className="col small">
                <b>{t('pub.log')}</b>
                {posted
                  .slice()
                  .reverse()
                  .slice(0, 20)
                  .map((p, k) => (
                    <div key={k} className="muted">
                      {p.at.slice(0, 16).replace('T', ' ')} · {p.job} · {p.platform} · {p.account}
                      {p.url && (
                        <>
                          {' · '}
                          <a href={p.url} onClick={(e) => (e.preventDefault(), void window.desk.openExternal(p.url!))}>
                            {t('pub.link')}
                          </a>
                        </>
                      )}
                    </div>
                  ))}
              </div>
            )}
          </div>
          <div className="right">
            <div className="browser-bar">
              <button className="btn sm" disabled={!browserOpen || !bstate?.canGoBack} onClick={() => window.desk.publish.navigate('back')}>
                ←
              </button>
              <button className="btn sm" disabled={!browserOpen || !bstate?.canGoForward} onClick={() => window.desk.publish.navigate('forward')}>
                →
              </button>
              <button className="btn sm" disabled={!browserOpen} onClick={() => window.desk.publish.navigate('reload')}>
                ⟳
              </button>
              <button className="btn sm" disabled={!browserOpen} onClick={() => window.desk.publish.navigate('upload')}>
                {t('pub.uploadPage')}
              </button>
              <span className="url mono">{browserOpen ? `${bstate?.loading ? '… ' : ''}${bstate?.url}` : ''}</span>
              <span className="badge">{account ? `persist:${adapterId}-${account}` : '-'}</span>
            </div>
            <div className="browser-slot" ref={slot}>
              {!browserOpen && <span>{account ? t('pub.slotHint') : t('pub.slotNoAccount')}</span>}
            </div>
          </div>
        </div>
      </div>
      {modal === 'confirm' && m && (
        <Modal title={t('pub.confirmTitle', { code: m.confirmation_code })} onClose={() => setModal(null)}>
          <div className="muted small">{t('pub.confirmBody')}</div>
          <table className="t small">
            <thead>
              <tr>
                <th>{t('pub.date')}</th>
                <th>{t('pub.platform')}</th>
                <th>{t('pub.job')}</th>
                <th>{t('pub.titleCol')}</th>
              </tr>
            </thead>
            <tbody>
              {m.items.map((i) => (
                <tr key={itemKey(i)}>
                  <td className="mono">
                    {i.date} {i.time}
                  </td>
                  <td>{i.platform}</td>
                  <td className="mono">{i.job}</td>
                  <td>{i.title}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row" style={{ justifyContent: 'flex-end' }}>
            <button className="btn" onClick={() => setModal(null)}>
              {t('common.cancel')}
            </button>
            <button
              className="btn primary"
              data-testid="pub-confirm-ok"
              onClick={() =>
                guard(async () => {
                  await window.desk.publish.confirmPackage(batch, m.confirmation_code);
                  setModal(null);
                  await refreshLocal();
                  if (isWork && client) setInfo(t('pkg.calendared', { n: await toCalendar(client, batch, m.items) }));
                })
              }
            >
              {t('pub.confirmBtn', { n: m.items.length })}
            </button>
          </div>
        </Modal>
      )}
      {modal === 'account' && adapter && (
        <AccountModal
          adapter={adapter}
          onClose={() => setModal(null)}
          onAdd={(name) =>
            guard(async () => {
              setAccounts(await window.desk.publish.addAccount(adapter.id, name));
              setAccount(name);
              setModal(null);
            })
          }
        />
      )}
      {modal === 'posted' && item && m && adapter && (
        <PostedModal
          adapter={adapter}
          onClose={() => setModal(null)}
          onOk={(url) =>
            guard(async () => {
              await window.desk.publish.markPosted({ batchId: batch, code: m.confirmation_code, job: item.job, platform: item.platform, adapterId, account, url: url || undefined });
              setModal(null);
              await refreshLocal();
              // the calendar shows it as posted too (its slot, or the matching planned post)
              if (client) {
                const cal = await client.calendar();
                const base = basePlatform(item.platform);
                const p = cal.posts.find((x) => x.item === batch && x.clip === item.job && x.platform.split(':')[0] === base && x.state !== 'posted');
                if (p) await client.updatePost(p.id, { state: 'posted' });
                setInfo(t('pub.postedCal'));
              }
            })
          }
        />
      )}
    </>
  );
}

function ItemRow({ i, on, posted, onClick }: { i: ManifestItem; on: boolean; posted: boolean; onClick: () => void }) {
  return (
    <div className={`item ${on ? 'on' : ''} ${posted ? 'posted' : ''}`} onClick={onClick} data-testid="pub-item" data-platform={i.platform} data-job={i.job}>
      <div className="row small">
        <span className="mono">
          {i.date} {i.time}
        </span>
        <span className="badge">{i.platform}</span>
        {basePlatform(i.platform).startsWith('youtube') && (
          <span className="badge" data-testid="pub-item-format" data-format={basePlatform(i.platform) === 'youtube-shorts' ? 'shorts' : 'long'}>
            {t(basePlatform(i.platform) === 'youtube-shorts' ? 'pf.yt.shorts' : 'pf.yt.long')}
          </span>
        )}
        {posted && <span className="badge accent">{t('pub.posted')}</span>}
        {(i.checks ?? []).filter((c) => c.code !== 'ai-label' && c.code !== 'no-title').length > 0 && (
          <span className="badge danger" data-testid="pkg-check-count">
            {(i.checks ?? []).filter((c) => c.code !== 'ai-label' && c.code !== 'no-title').length}
          </span>
        )}
      </div>
      <div>{i.title || i.job}</div>
    </div>
  );
}

function AccountModal({ adapter, onClose, onAdd }: { adapter: Adapter; onClose: () => void; onAdd: (n: string) => void }) {
  const [v, setV] = useState('');
  const ok = /^[a-z0-9][a-z0-9_-]{0,31}$/.test(v);
  return (
    <Modal title={t('pub.addAccountTitle', { p: adapter.name })} onClose={onClose}>
      <div className="muted small">{t('pub.addAccountBody')}</div>
      <input className="input" value={v} placeholder="main" onChange={(e) => setV(e.target.value.toLowerCase())} maxLength={32} autoFocus />
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <button className="btn" onClick={onClose}>
          {t('common.cancel')}
        </button>
        <button className="btn primary" disabled={!ok} onClick={() => onAdd(v)}>
          {t('common.ok')}
        </button>
      </div>
    </Modal>
  );
}

function PostedModal({ adapter, onClose, onOk }: { adapter: Adapter; onClose: () => void; onOk: (url: string) => void }) {
  const [url, setUrl] = useState('');
  const valid = !url || /^https:\/\/\S+$/.test(url);
  return (
    <Modal title={t('pub.markPosted')} onClose={onClose}>
      <div className="muted small">{t('pub.postedBody', { p: adapter.name })}</div>
      <input className="input" value={url} placeholder="https://…" onChange={(e) => setUrl(e.target.value.trim())} />
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <button className="btn" onClick={onClose}>
          {t('common.cancel')}
        </button>
        <button className="btn primary" disabled={!valid} onClick={() => onOk(url)} data-testid="pub-posted-ok">
          {t('pub.markPostedBtn')}
        </button>
      </div>
    </Modal>
  );
}

export function checkText(c: PackageCheck): string {
  return tk(`pkg.c.${c.code}`, { n: c.n ?? '', max: c.max ?? '', min: c.min ?? '', want: c.want ?? '', got: c.got ?? '' });
}

/** Confirmed work package -> one calendar slot per item (its date / time / platform); existing slots are kept. */
export async function toCalendar(client: NonNullable<ReturnType<typeof useEngine>['client']>, batch: string, items: ManifestItem[]): Promise<number> {
  const cal = await client.calendar();
  let n = 0;
  for (const i of items) {
    const platform = basePlatform(i.platform);
    if (cal.posts.some((p) => p.item === batch && p.clip === i.job && p.platform.split(':')[0] === platform)) continue;
    await client.schedule({ item: batch, clip: i.job, at: `${i.date}T${i.time}`, platform });
    n++;
  }
  return n;
}

const PKG_PLATFORMS_KEY = 'pkg.platforms';

function WorkPackageCard({ batch, busy, onDone, guard }: { batch: string; busy: boolean; onDone: () => void; guard: (fn: () => Promise<unknown>) => Promise<void> }) {
  const { client } = useEngine();
  const clips = useLoad((c) => c.clips(batch), [batch]);
  const ready = (clips.data?.clips ?? []).filter((c) => c.files.length > 0 && !c.extra && c.state !== 'running' && c.state !== 'queued');
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const [pfs, setPfs] = useState<string[]>(() => {
    try {
      const v = JSON.parse(localStorage.getItem(PKG_PLATFORMS_KEY) || 'null');
      if (Array.isArray(v) && v.every((x) => SCHEDULE_PLATFORMS.includes(x))) return v;
    } catch {
      /* default */
    }
    return ['xiaohongshu', 'douyin'];
  });
  const [perDay, setPerDay] = useState(1);
  const [start, setStart] = useState('');
  const [times, setTimes] = useState('19:00');
  const sel = picked ?? new Set(ready.map((c) => c.id));
  const toggle = (id: string) => setPicked(() => {
    const n = new Set(sel);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    return n;
  });
  const connected = useConnectedPlatforms();
  const setPfsSaved = (n: string[]) => {
    setPfs(n);
    try {
      localStorage.setItem(PKG_PLATFORMS_KEY, JSON.stringify(n));
    } catch {
      /* private mode */
    }
  };
  const n = sel.size * pfs.length;
  return (
    <div className="card col" data-testid="pkg-card">
      <b>{t('pkg.title')}</b>
      <span className="muted small">{t('pkg.hint')}</span>
      <b className="small">{t('pkg.clips')}</b>
      {clips.data && !ready.length && <span className="muted small">{t('pkg.none')}</span>}
      <div className="col" style={{ gap: 4 }}>
        {ready.map((c) => (
          <label key={c.id} className="row small" style={{ gap: 6 }} data-testid="pkg-clip">
            <input type="checkbox" checked={sel.has(c.id)} onChange={() => toggle(c.id)} />
            <span className="clamp1">{c.title || c.id}</span>
            <span className="muted mono">{c.files.map((f) => f.aspect).join(' · ')}</span>
          </label>
        ))}
      </div>
      <b className="small">{t('pkg.platforms')}</b>
      <PlatformPicker multi value={pfs} onChange={setPfsSaved} connected={connected} testId="pkg-platform" />
      <div className="row">
        <Field label={t('pub.perDay')}>
          <input className="input" type="number" min={1} max={20} value={perDay} onChange={(e) => setPerDay(Math.max(1, Number(e.target.value) || 1))} style={{ width: 70 }} />
        </Field>
        <Field label={t('pub.start')}>
          <input className="input" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </Field>
        <Field label={t('pub.times')}>
          <input className="input" value={times} onChange={(e) => setTimes(e.target.value)} style={{ width: 120 }} />
        </Field>
      </div>
      <button
        className="btn primary"
        disabled={busy || !n || !client}
        data-testid="pkg-go"
        onClick={() =>
          guard(async () => {
            // each account's default post times (发布账号) win over the common times for its platform
            const chans = await window.desk.publish.channels().catch(() => []);
            const ads = (await window.desk.publish.adapters()).adapters;
            const byPf: Record<string, string[]> = {};
            for (const c of chans) {
              const a = ads.find((x) => x.id === c.adapterId);
              for (const p of a?.packagePlatforms ?? []) if (pfs.includes(p) && c.times.length && !byPf[p]) byPf[p] = c.times;
            }
            await client!.packageWork(batch, {
              clips: ready.filter((c) => sel.has(c.id)).map((c) => c.id),
              platforms: pfs,
              per_day: perDay,
              start: start || undefined,
              times: times.split(/[,，\s]+/).map((x) => x.trim()).filter(Boolean),
              times_by_platform: byPf,
            });
            onDone();
          })
        }
      >
        {t('pkg.go', { n })}
      </button>
    </div>
  );
}
