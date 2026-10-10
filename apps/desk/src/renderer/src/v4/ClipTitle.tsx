// The clip's one title, edited in place in the editor header: the pencil (or a double-click) turns it into a field,
// Enter / leaving the field saves it, Escape puts it back, an empty field goes back to the AI's title. Every publish
// card of the clip follows (a platform with its own title keeps that one).
import { useEffect, useRef, useState } from 'react';
import { Pencil } from 'lucide-react';
import { t } from '../i18n';
import { useEngine } from '../lib/engine';
import { errText } from './msg';
import { useUi } from './ui';

export function ClipTitle({ item, clip, title, custom, onSaved }: { item: string; clip: string; title: string; custom?: boolean; onSaved?: () => void }) {
  const { client } = useEngine();
  const ui = useUi();
  const [edit, setEdit] = useState(false);
  const [v, setV] = useState(title);
  const [shown, setShown] = useState(title);
  const inp = useRef<HTMLInputElement>(null);
  const done = useRef(false);
  useEffect(() => setShown(title), [title]);
  useEffect(() => {
    if (edit) inp.current?.select();
  }, [edit]);

  const open = () => {
    done.current = false;
    setV(shown);
    setEdit(true);
  };
  const save = async () => {
    if (done.current) return;
    done.current = true;
    setEdit(false);
    const x = v.trim();
    if (!client || x === shown) return;
    const before = shown;
    setShown(x || before);
    try {
      const r = await client.setClipTitle(item, clip, x || null);
      setShown(r.title);
      ui.toast(t('ct.saved'), {
        undo: async () => {
          const u = await client.setClipTitle(item, clip, before); // the AI's own title back = not hers any more
          setShown(u.title);
          onSaved?.();
        },
      });
      onSaved?.();
    } catch (e) {
      setShown(before);
      ui.toast(errText(e), { error: true });
    }
  };

  if (edit)
    return (
      <input
        ref={inp}
        className="ct-input"
        value={v}
        maxLength={300}
        lang="zh-CN"
        aria-label={t('ct.label')}
        placeholder={t('ct.placeholder')}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => void save()}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === 'Enter') void save();
          if (e.key === 'Escape') {
            done.current = true;
            setEdit(false);
          }
        }}
        data-testid="editor-title-input"
      />
    );
  return (
    <>
      <h1 className="clamp1" lang="zh-CN" data-testid="editor-title" data-custom={custom ? '1' : undefined} onDoubleClick={open} title={t('ct.hint')}>
        {shown}
      </h1>
      <button className="btn ghost icon sm ct-edit" onClick={open} aria-label={t('ct.label')} data-tip={t('ct.hint')} data-testid="editor-title-edit">
        <Pencil className="ico" />
      </button>
    </>
  );
}
