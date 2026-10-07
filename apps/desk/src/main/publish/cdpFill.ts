// Executes a fill plan over the Chrome DevTools Protocol (webContents.debugger). Element lookups run in an
// isolated world per frame (page scripts cannot see or tamper with them); files go through
// DOM.setFileInputFiles; text is typed with Input.insertText like a keyboard would. Nothing is ever clicked.
import type { FillStep } from '../../shared/publish/fillPlan';

export type Send = (method: string, params?: Record<string, unknown>) => Promise<any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export interface StepResult {
  field: string;
  kind: FillStep['kind'];
  status: 'ok' | 'not-found' | 'error';
  detail?: string;
}

const WORLD = 'vstudio-desk-fill';

const ALLOWED_METHODS = new Set([
  'Page.getFrameTree',
  'Page.createIsolatedWorld',
  'Runtime.evaluate',
  'Runtime.callFunctionOn',
  'Runtime.releaseObject',
  'DOM.setFileInputFiles',
  'Input.insertText',
  'Input.dispatchKeyEvent',
  'Emulation.setFocusEmulationEnabled',
]);

/** Wraps a raw sender so only the commands assisted fill needs can be sent (no Input.dispatchMouseEvent,
 * no Network.getCookies, no Storage.*). Enter is the only key that may be dispatched. */
export function guardedSend(raw: Send): Send {
  return async (method, params) => {
    if (!ALLOWED_METHODS.has(method)) throw new Error(`CDP method not allowed: ${method}`);
    if (method === 'Input.dispatchKeyEvent' && (params as { key?: string })?.key !== 'Enter') {
      throw new Error('only Enter may be dispatched');
    }
    return raw(method, params);
  };
}

/** First element matching any selector; for fields to type into, only rendered (visible) ones count - file
 * inputs are usually hidden on purpose, so they are taken as they are. Open shadow roots are searched too
 * (视频号助手 renders its pages inside a micro-frontend's shadow DOM). */
function findExpr(selectors: string[], visible: boolean): string {
  const vis = visible ? '&& el.getClientRects().length > 0' : '';
  return `(() => {
  const roots = [document];
  for (let i = 0; i < roots.length && i < 400; i++) {
    for (const el of roots[i].querySelectorAll('*')) if (el.shadowRoot) roots.push(el.shadowRoot);
  }
  for (const s of ${JSON.stringify(selectors)}) { for (const r of roots) { try { for (const el of r.querySelectorAll(s)) { if (el ${vis}) return el; } } catch (e) {} } }
  return null; })()`;
}

const FOCUS_FN = `function (clear) {
  this.scrollIntoView({ block: 'center' });
  this.focus();
  if (!clear) return true;
  if (this.isContentEditable) {
    const r = document.createRange(); r.selectNodeContents(this);
    const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
  } else if (typeof this.select === 'function') { this.select(); }
  return true;
}`;

const IS_FILE_INPUT_FN = `function () { return this.tagName === 'INPUT' && this.type === 'file'; }`;

const HIGHLIGHT_FN = `function () {
  this.scrollIntoView({ block: 'center' });
  this.style.outline = '3px solid #2DD4BF'; this.style.outlineOffset = '3px';
  return true;
}`;

interface Frame {
  frame: { id: string };
  childFrames?: Frame[];
}

function frameIds(t: Frame): string[] {
  return [t.frame.id, ...(t.childFrames ?? []).flatMap(frameIds)];
}

export async function findElement(send: Send, selectors: string[], visible = false): Promise<string | null> {
  const { frameTree } = await send('Page.getFrameTree');
  for (const frameId of frameIds(frameTree)) {
    let ctx: number;
    try {
      ({ executionContextId: ctx } = await send('Page.createIsolatedWorld', { frameId, worldName: WORLD }));
    } catch {
      continue; // frame went away / out-of-process frame
    }
    const r = await send('Runtime.evaluate', { expression: findExpr(selectors, visible), contextId: ctx, returnByValue: false });
    if (r?.result?.subtype === 'node' && r.result.objectId) return r.result.objectId as string;
  }
  return null;
}

async function waitFor(send: Send, selectors: string[], visible: boolean, timeoutMs: number, sleep: (ms: number) => Promise<void>): Promise<string | null> {
  const t0 = Date.now();
  for (;;) {
    const id = await findElement(send, selectors, visible);
    if (id || Date.now() - t0 >= timeoutMs) return id;
    await sleep(400);
  }
}

async function call(send: Send, objectId: string, fn: string, args: unknown[] = []): Promise<unknown> {
  const r = await send('Runtime.callFunctionOn', {
    objectId,
    functionDeclaration: fn,
    arguments: args.map((value) => ({ value })),
    returnByValue: true,
  });
  return r?.result?.value;
}

async function typeText(send: Send, text: string, editable: 'input' | 'contenteditable') {
  if (editable === 'input') {
    await send('Input.insertText', { text: text.replace(/\s*\n\s*/g, ' ') });
    return;
  }
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i++) {
    if (i > 0) {
      await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r' });
      await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
    }
    if (lines[i]) await send('Input.insertText', { text: lines[i] });
  }
}

export async function runFill(
  rawSend: Send,
  steps: FillStep[],
  opts: { sleep?: (ms: number) => Promise<void>; onStep?: (r: StepResult) => void } = {},
): Promise<StepResult[]> {
  const send = guardedSend(rawSend);
  const sleep = opts.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  const out: StepResult[] = [];
  const push = (r: StepResult) => {
    out.push(r);
    opts.onStep?.(r);
  };
  // the platform view usually does not have keyboard focus (the creator just clicked in the desk UI):
  // emulate focus so element.focus() + Input.insertText land in the field
  await send('Emulation.setFocusEmulationEnabled', { enabled: true }).catch(() => undefined);
  for (const step of steps) {
    try {
      const id = await waitFor(send, step.selectors, step.kind !== 'files', step.timeoutMs, sleep);
      if (!id) {
        push({ field: step.field, kind: step.kind, status: 'not-found', detail: step.selectors[0] });
        if (step.field === 'file') break; // nothing else appears before the upload starts
        continue;
      }
      if (step.kind === 'files') {
        if (!(await call(send, id, IS_FILE_INPUT_FN))) {
          push({ field: step.field, kind: step.kind, status: 'error', detail: 'selector is not a file input' });
          if (step.field === 'file') break;
          continue;
        }
        await send('DOM.setFileInputFiles', { files: step.paths, objectId: id });
      } else if (step.kind === 'text') {
        await call(send, id, FOCUS_FN, [step.clear]);
        if (step.items) {
          for (const it of step.items) {
            await send('Input.insertText', { text: it.replace(/\s+/g, ' ') });
            await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r' });
            await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
            await sleep(150);
          }
        } else {
          await typeText(send, step.text, step.editable);
        }
      } else {
        await call(send, id, HIGHLIGHT_FN);
      }
      await send('Runtime.releaseObject', { objectId: id }).catch(() => undefined);
      push({ field: step.field, kind: step.kind, status: 'ok' });
    } catch (e) {
      push({ field: step.field, kind: step.kind, status: 'error', detail: (e as Error).message });
      if (step.field === 'file') break;
    }
  }
  await send('Emulation.setFocusEmulationEnabled', { enabled: false }).catch(() => undefined);
  return out;
}
