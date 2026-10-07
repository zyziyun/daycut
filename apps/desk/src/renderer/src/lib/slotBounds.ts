// Where the embedded platform browser goes: the slot's on-screen rectangle, clipped to the window. A slot scrolled
// partly above the top (Publishing accounts: "Add account" on a row below the fold) has a negative top, which the
// publish:setBounds IPC schema refuses (x / y >= 0): the browser then never moved and the call threw.
export interface Bounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export const HIDDEN: Bounds = { x: 0, y: 0, width: 0, height: 0 };

export function slotBounds(r: Pick<DOMRect, 'left' | 'top' | 'right' | 'bottom'>, view: { width: number; height: number }): Bounds {
  const x0 = Math.max(0, Math.round(r.left));
  const y0 = Math.max(0, Math.round(r.top));
  const x1 = Math.min(Math.round(view.width), Math.round(r.right));
  const y1 = Math.min(Math.round(view.height), Math.round(r.bottom));
  if (x1 <= x0 || y1 <= y0) return HIDDEN;
  return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
}

/** setBounds for a slot element (hidden when `show` is false or the slot is off screen); never rejects. */
export function placeBrowser(el: HTMLElement, show: boolean) {
  const b = show ? slotBounds(el.getBoundingClientRect(), { width: window.innerWidth, height: window.innerHeight }) : HIDDEN;
  void window.desk.publish.setBounds(b)?.catch?.(() => undefined);
}
