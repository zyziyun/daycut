"""Review: a static HTML grid page + a combined "decisions needed" sheet; decisions come back as JSON.

``review``            -> <batch>/review/index.html (contact sheet + 3 s snippet + QC light + reasons per job;
                         keys: arrows / j k move, space approve, x reject with a reason, u undo, d download) and
                         <batch>/review/decisions_needed.md (every cleanup edit still waiting for the creator's yes,
                         across all jobs: "N jobs, M edits to confirm").
The page writes nothing itself (static file): its "Download decisions.json" button saves
  {"batch": name, "decisions": {job: {"decision": "approve"|"reject", "reason": ".."}},
   "cleanup": {job: "确认 3,5 / 保留 7"}}
``review --apply decisions.json``: approve -> ``approved``; reject -> ``needs-replan`` with the reason (shown by
``status``; the planner / a Claude Code agent turns it into a changed job row, then ``plan`` again); a cleanup
reply -> stored in the job's params and the job goes back to ``planned`` (``run`` re-cuts from ``apply`` on).
Bulk answers in the same file: ``"confirm_kinds": ["filler-merged", "filler/lead"]`` (or ``{"ep03": [...], "*":
[...]}``) approves every open question of those classes (``vstudio.cleanup.edit_class``; a bare kind matches all
its sub-classes); ``"accept_policy": true`` also cuts the edits the confirm policy approved after the job was
rendered. Every reply is learned (``vstudio.cleanup.learn``, per persona, outside the repo) so the policy asks less
next time. The page shows the CURRENT policy's view (re-evaluated from each job's EDL), caption fixes that are
guesses (``vstudio.proofread.flag_guesses``) in yellow.
"""
import html
import json
import os

from .store import Store
from .util import read_json, write_json

REVIEW_STATES = ("done", "approved", "needs-replan", "packaged")


def _rel(path, base):
    return os.path.relpath(path, base) if path else None


def _row(e):
    from vstudio import cleanup as C
    return dict(id=e["id"], part=e.get("part", "body"), kind=e["kind"], cls=C.edit_class(e), text=e.get("text", ""),
                t0=e.get("t0"), t1=e.get("t1"), before=e.get("before", ""), after=e.get("after", ""),
                reason=e.get("reason", ""), confidence=e.get("confidence"))


def cleanup_view(rows, params, pol=None):
    """The job's cleanup questions under the CURRENT policy: the EDL(s) of the cleanup stage re-evaluated with
    ``vstudio.cleanup.apply_policy`` (cheap, no audio). -> dict(confirm=[rows], edits=[all edits, with ``rendered``
    = the action the render used], policy=dict(asked, auto, keep, pending=[ids the policy cuts that the render
    did not cut yet])). Falls back to confirm.json when the EDL is gone."""
    from vstudio import cleanup as C
    cl = (rows.get("cleanup") or {}).get("out") or {}
    on = params.get("cleanup_policy", True) is not False and params.get("cleanup_profile") != "off"
    pol = pol if pol is not None else (C.load_policy() if on else None)
    edits = []
    for part in ("body", "hook"):
        path = cl.get(part)
        E = read_json(path, None) if path and os.path.exists(path) else None
        if not E:
            continue
        eds = E.get("edits") or []
        for e in eds:
            e["part"], e["rendered"] = part, e["action"]
        if on:
            C.apply_policy(eds, E.get("words") or [], pol)
        edits += eds
    if not edits:
        confirm = read_json(cl.get("confirm_file"), []) if cl.get("confirm_file") else []
        return dict(confirm=[_row(e) for e in confirm], edits=None, policy=None)
    pc = C.policy_counts(edits)
    pc["pending"] = [e["id"] for e in edits if e["action"] == "auto" and e["rendered"] != "auto"]
    return dict(confirm=[_row(e) for e in edits if e["action"] == "confirm"], edits=edits, policy=pc)


def _captions(rows, store, prr):
    from vstudio import proofread as PR
    changes = [dict(c) for c in prr.get("changes") or []]
    if changes and any("guess" not in c for c in changes):        # reports written before the guess flags
        g = ((rows.get("glossary") or {}).get("out") or {}).get("glossary")
        from .stages import _gloss_context
        PR.flag_guesses(changes, read_json(g, {}) if g else None, dict(glossary=_gloss_context(store.spec)))
    return dict(provider=prr.get("provider"), model=prr.get("model"),
                changes=[dict(i=c["i"], start=c.get("start"), before=c["before"], after=c["after"],
                              source=c.get("source"), why=c.get("why", ""), guess=bool(c.get("guess")),
                              support=c.get("support", "")) for c in changes],
                rejected=len(prr.get("rejected") or []), low=prr.get("low_confidence") or [],
                fillers=prr.get("fillers_left") or [])


def collect(store):
    from vstudio import cleanup as C
    base = os.path.join(store.dir, "review")
    out = []
    pol = C.load_policy()
    for j in store.jobs(REVIEW_STATES + ("failed",)):
        rows = store.stage_rows(j["id"])
        pv = (rows.get("preview") or {}).get("out") or {}
        ex = (rows.get("export") or {}).get("out") or {}
        cm = (rows.get("compose") or {}).get("out") or {}
        view = cleanup_view(rows, j["params"] or {}, pol)
        confirm = view["confirm"]
        pr = (rows.get("proofread") or {}).get("out") or {}
        prr = read_json(pr.get("report"), {}) if pr.get("report") else {}
        captions = _captions(rows, store, prr)
        p = j["params"] or {}
        out.append(dict(
            id=j["id"], item=j["item"], variant=j["variant"], state=j["state"], qc=j["qc"] or "none",
            reasons=(j["qc_reasons"] or {}).get("red", []) if isinstance(j["qc_reasons"], dict) else [],
            warnings=(j["qc_reasons"] or {}).get("warn", []) if isinstance(j["qc_reasons"], dict) else [],
            sample=bool(j["sample"]), pilot=bool(j["pilot"]), review=j["review"], review_reason=j["review_reason"],
            title=p.get("title") or "", platforms=p.get("platforms") or [], range=p.get("range"),
            hook=(p.get("hook") or {}).get("lines") or [], duration=cm.get("duration"),
            sheet=_rel(pv.get("sheet"), base), snippet=_rel(pv.get("snippet"), base),
            files=[_rel(e["file"], base) for e in ex.get("exports") or []],
            confirm=confirm, policy=view["policy"], reply=p.get("cleanup_reply") or "", captions=captions))
    return out


def _caption_md(it):
    cap = it.get("captions") or {}
    lines = []
    if cap.get("changes"):
        ng = sum(bool(c.get("guess")) for c in cap["changes"])
        lines += ["", f"Caption corrections ({cap.get('provider')}{' ' + cap['model'] if cap.get('model') else ''}) - "
                      "check them, the audio is unchanged" + (f"; **{ng} GUESS(ES)**: not backed by the glossary or a "
                                                              "strong sound-alike - a human must look" if ng else "")
                  + ":", "", "| cue | at | check | before | after | source | why |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {c['i']} | {c.get('start') or 0:.1f}s | "
                  f"{'<mark>**GUESS**</mark> ' + c.get('support', '') if c.get('guess') else 'ok'} | "
                  f"{c['before']} | {c['after']} | {c.get('source')} | {c.get('why', '')} |" for c in cap["changes"]]
    if cap.get("low"):
        lines += ["", "Low-confidence words (ASR probability): " +
                  ", ".join(f"{x['word']} ({x['p']:.2f}) @{x['t']:.1f}s" for x in cap["low"][:30])]
    if cap.get("fillers"):
        lines += ["", "Fillers still spoken (captions match the audio; cut them with the cleanup reply - the matching "
                      "edit id is in the table above - or leave them):"]
        lines += [f"- {f['start']:.1f}s `{f['text']}` -> {', '.join(f['fillers'])}" for f in cap["fillers"]]
    return lines


def policy_totals(items):
    """Batch totals of the confirm policy over review items: asked / auto / keep / pending."""
    t = dict(asked=0, auto=0, keep=0, pending=0)
    for it in items:
        pc = it.get("policy") or {}
        for k in ("asked", "auto", "keep"):
            t[k] += int(pc.get(k) or 0)
        t["pending"] += len(pc.get("pending") or [])
    return t


def decisions_needed_md(items, name):
    pend = [it for it in items if (it["confirm"] or _caption_md(it)) and it["state"] != "packaged"]
    n = sum(len(it["confirm"]) for it in pend)
    pt = policy_totals(items)
    classes = {}
    for it in pend:
        for e in it["confirm"]:
            classes[e.get("cls") or e["kind"]] = classes.get(e.get("cls") or e["kind"], 0) + 1
    guesses = sum(bool(c.get("guess")) for it in pend for c in (it.get("captions") or {}).get("changes") or [])
    lines = [f"# Decisions needed - {name}", "",
             f"{len(pend)} job(s), {n} cleanup edit(s) waiting for a yes. Only AUTO edits are cut until you reply.",
             "Reply per job in the review page (or in decisions.json under \"cleanup\"), e.g. `确认 3,5 / 保留 7`, "
             "`全部确认`."]
    if pt["auto"] or pt["keep"]:
        lines.append(f"Confirm policy answered {pt['auto'] + pt['keep']} of {pt['auto'] + pt['keep'] + pt['asked']} "
                     f"questions ({pt['auto']} cut, {pt['keep']} kept)" +
                     (f"; {pt['pending']} of its cuts are not in the rendered files yet (`\"accept_policy\": true` in "
                      "decisions.json / `review --accept-policy`, or `run --jobs <ids>` re-runs cleanup)" if pt["pending"] else "") + ".")
    if classes:
        lines.append("Bulk: `{\"confirm_kinds\": [...]}` in decisions.json cuts every open question of a class: " +
                     ", ".join(f"`{k}` ({v})" for k, v in sorted(classes.items(), key=lambda kv: -kv[1])) + ".")
    if guesses:
        lines.append(f"<mark>**{guesses} caption fix(es) are GUESSES**</mark> (marked below): look at each one.")
    lines.append("")
    for it in pend:
        lines += [f"## {it['id']}  {it['title']}", ""]
        pc = it.get("policy") or {}
        if pc.get("auto") or pc.get("keep"):
            lines += [f"policy: {pc.get('auto', 0)} cut, {pc.get('keep', 0)} kept without asking" +
                      (f" (ids {', '.join(map(str, pc['pending']))} cut once accepted / re-run)" if pc.get("pending") else ""), ""]
        if it["confirm"]:
            lines += ["| id | part | class | text | context | why |", "|---|---|---|---|---|---|"]
        for e in it["confirm"]:
            ctx = f"…{e.get('before', '')[-14:]} [{e.get('text', '')}] {e.get('after', '')[:14]}…"
            lines.append(f"| {e['id']} | {e['part']} | {e.get('cls') or e['kind']} | {e.get('text', '')} | {ctx} | "
                         f"{e.get('reason', '')} |")
        if it["reply"]:
            lines.append(f"\ncurrent reply: `{it['reply']}`")
        lines += _caption_md(it)
        lines.append("")
    return "\n".join(lines), len(pend), n


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Review - __NAME__</title>
<style>
body{font:14px/1.4 -apple-system,system-ui,sans-serif;margin:0;background:#111;color:#eee}
header{position:sticky;top:0;background:#1b1b1b;padding:10px 16px;display:flex;gap:12px;align-items:center;z-index:2;
border-bottom:1px solid #333;flex-wrap:wrap}
header button{background:#2a2a2a;color:#eee;border:1px solid #444;border-radius:6px;padding:4px 10px;cursor:pointer}
header button.on{border-color:#2dd4bf}
#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;padding:16px}
.card{background:#1c1c1c;border:2px solid #2a2a2a;border-radius:10px;padding:8px;position:relative}
.card.focus{border-color:#2dd4bf}.card.approve{background:#12291f}.card.reject{background:#2d1515}
.card img,.card video{width:100%;border-radius:6px;display:block;background:#000}
.light{display:inline-block;width:12px;height:12px;border-radius:50%;vertical-align:middle;margin-right:6px}
.green{background:#22c55e}.red{background:#ef4444}.none{background:#777}
.meta{font-size:12px;color:#aaa}.reasons{color:#fca5a5;font-size:12px;margin:4px 0}.warn{color:#fcd34d;font-size:12px}
.badge{font-size:11px;border:1px solid #666;border-radius:4px;padding:0 4px;margin-left:4px}
.dec{font-weight:600;margin-top:4px}
#needed{padding:0 16px 40px}#needed table{border-collapse:collapse;font-size:12px;margin-bottom:8px}
#needed td,#needed th{border:1px solid #333;padding:3px 6px}#needed input{width:320px;background:#222;color:#eee;
border:1px solid #444;padding:4px}
kbd{background:#333;border-radius:3px;padding:0 4px}
.caps{margin-top:6px}.cap{font-size:12px;border-top:1px solid #333;padding:3px 0}.cap s{color:#f87171}.cap b{color:#86efac}
.cap.guess{background:#3b3305;border-left:3px solid #facc15;padding-left:4px}.badge.guess{border-color:#facc15;color:#facc15}
#needed tr.bulk td{background:#12291f}#bulk button{background:#2a2a2a;color:#eee;border:1px solid #444;border-radius:6px;
padding:3px 8px;margin:2px;cursor:pointer}#bulk button.on{border-color:#22c55e;background:#12291f}
</style></head><body>
<header><b>__NAME__</b><span id="count"></span>
<span>filter:</span><button data-f="all" class="on">all</button><button data-f="red">red</button>
<button data-f="sample">sampled</button><button data-f="open">undecided</button>
<span class="meta"><kbd>space</kbd> approve <kbd>x</kbd> reject <kbd>u</kbd> undo <kbd>j</kbd>/<kbd>k</kbd> move
<kbd>d</kbd> download</span><button id="dl">Download decisions.json</button></header>
<div id="grid"></div><div id="needed"></div>
<script>
const DATA = __DATA__; const NAME = __NAMEJS__; const KEY = "vstudio-batch-review:" + NAME;
let st = JSON.parse(localStorage.getItem(KEY) || '{"decisions":{},"cleanup":{}}');
st.kinds = st.kinds || []; st.accept = !!st.accept;
let filt = "all", focus = 0;
const save = () => localStorage.setItem(KEY, JSON.stringify(st));
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function visible(){return DATA.items.filter(it => filt=="all" || (filt=="red" && it.qc=="red") ||
  (filt=="sample" && it.sample) || (filt=="open" && !st.decisions[it.id]));}
function cap(it){ return it.captions || {changes: [], low: [], fillers: []}; }
function capHtml(it){
  const c = cap(it); if (!c.changes.length && !c.low.length && !c.fillers.length) return "";
  const ng = c.changes.filter(x => x.guess).length;
  let h = `<details class="caps"${ng ? " open" : ""}><summary class="meta">captions: ${c.changes.length} corrected (${esc(c.provider||"-")}${ng ? `, <span style="color:#facc15">${ng} guess${ng > 1 ? "es" : ""}</span>` : ""}),
    ${c.low.length} low-confidence, ${c.fillers.length} filler line(s)</summary>`;
  c.changes.forEach(x => { h += `<div class="cap${x.guess ? " guess" : ""}"><span class="meta">#${x.i} ${x.start != null ? x.start.toFixed(1) + "s" : ""}
    ${esc(x.source)}</span>${x.guess ? ' <b style="color:#facc15">GUESS - look</b>' : ""}<br><s>${esc(x.before)}</s><br><b>${esc(x.after)}</b>${x.why ? ` <span class="meta">(${esc(x.why)})</span>` : ""}${x.guess ? `<div class="meta">${esc(x.support)}</div>` : ""}</div>`; });
  if (c.low.length) h += `<div class="cap meta">unsure: ${c.low.map(x => `${esc(x.word)} <i>${x.p.toFixed(2)}</i> @${x.t.toFixed(1)}s`).join(", ")}</div>`;
  c.fillers.forEach(x => { h += `<div class="cap warn">${x.start.toFixed(1)}s ${esc(x.text)} → ${esc(x.fillers.join(", "))}</div>`; });
  return h + "</details>";
}
function render(){
  const g = document.getElementById("grid"); const v = visible(); g.innerHTML = "";
  focus = Math.min(focus, Math.max(0, v.length - 1));
  v.forEach((it, i) => {
    const d = st.decisions[it.id] || (it.review ? {decision: it.review == "approved" ? "approve" : "", reason: it.review_reason} : null);
    const c = document.createElement("div");
    c.className = "card" + (i == focus ? " focus" : "") + (d && d.decision ? " " + d.decision : "");
    c.innerHTML = `<div><span class="light ${it.qc}"></span><b>${esc(it.id)}</b>
      ${it.sample ? '<span class="badge">sample</span>' : ''}${it.pilot ? '<span class="badge">pilot</span>' : ''}
      ${it.confirm.length ? `<span class="badge">${it.confirm.length} to confirm</span>` : ''}
      ${cap(it).changes.length ? `<span class="badge">${cap(it).changes.length} caption fix${cap(it).changes.length > 1 ? "es" : ""}</span>` : ''}
      ${cap(it).changes.some(x => x.guess) ? `<span class="badge guess">${cap(it).changes.filter(x => x.guess).length} guess</span>` : ''}
      ${cap(it).low.length ? `<span class="badge">${cap(it).low.length} unsure word${cap(it).low.length > 1 ? "s" : ""}</span>` : ''}</div>
      <div>${esc(it.title)}</div>
      <div class="meta">${esc((it.platforms||[]).join(", "))} · ${it.duration ? it.duration.toFixed(1) + "s" : "-"}
      ${it.range ? " · src " + it.range.map(x => x.toFixed(1)).join("-") : ""} · ${esc(it.state)}</div>
      ${it.sheet ? `<a href="${esc(it.files[0]||it.sheet)}" target="_blank"><img src="${esc(it.sheet)}" loading="lazy"></a>` : ""}
      ${it.snippet ? `<video src="${esc(it.snippet)}" muted loop playsinline preload="metadata" style="margin-top:6px;max-height:320px;object-fit:contain"></video>` : ""}
      ${it.reasons.map(r => `<div class="reasons">${esc(r)}</div>`).join("")}
      ${it.warnings.slice(0,3).map(r => `<div class="warn">${esc(r)}</div>`).join("")}
      ${capHtml(it)}
      <div class="dec">${d && d.decision ? esc(d.decision + (d.reason ? ": " + d.reason : "")) : ""}</div>`;
    const vid = c.querySelector("video");
    if (vid) { c.onmouseenter = () => vid.play(); c.onmouseleave = () => vid.pause(); }
    c.onclick = () => { focus = i; render(); };
    g.appendChild(c);
  });
  const n = Object.keys(st.decisions).length;
  document.getElementById("count").textContent = `${n}/${DATA.items.length} decided`;
}
function renderNeeded(){
  const box = document.getElementById("needed"); const pend = DATA.items.filter(it => it.confirm.length);
  // caption corrections / unsure words are listed on each card (details) and in decisions_needed.md
  if (!pend.length) { box.innerHTML = ""; return; }
  const pol = DATA.items.reduce((a, it) => { const p = it.policy || {}; a.auto += p.auto || 0; a.keep += p.keep || 0;
    a.pending += (p.pending || []).length; return a; }, {auto: 0, keep: 0, pending: 0});
  const cls = {}; pend.forEach(it => it.confirm.forEach(e => { const k = e.cls || e.kind; cls[k] = (cls[k] || 0) + 1; }));
  const on = e => st.kinds.some(k => k == "*" || k == (e.cls || e.kind) || k == e.kind || (e.cls || "").startsWith(k + "/"));
  let h = `<h2>Decisions needed: ${pend.length} job(s), ${pend.reduce((a, it) => a + it.confirm.length, 0)} cleanup edit(s)</h2>
    <p class="meta">Only AUTO edits are cut. Reply per job, e.g. <code>确认 3,5 / 保留 7</code> or <code>全部确认</code>.
    ${pol.auto + pol.keep ? `The confirm policy already answered ${pol.auto + pol.keep} (${pol.auto} cut, ${pol.keep} kept).` : ""}</p>
    ${pol.pending ? `<label class="meta"><input type="checkbox" id="acc" ${st.accept ? "checked" : ""} style="width:auto">
      also cut the ${pol.pending} policy approvals that are not in the rendered files yet</label>` : ""}
    <div id="bulk"><span class="meta">confirm every open question of a kind:</span>
    ${Object.entries(cls).sort((a, b) => b[1] - a[1]).map(([k, n]) =>
      `<button data-k="${esc(k)}" class="${st.kinds.includes(k) ? "on" : ""}">${esc(k)} (${n})</button>`).join("")}</div>`;
  pend.forEach(it => {
    h += `<h3>${esc(it.id)} ${esc(it.title)}</h3><table><tr><th>id</th><th>part</th><th>kind</th><th>context</th><th>why</th></tr>`;
    it.confirm.forEach(e => { h += `<tr class="${on(e) ? "bulk" : ""}"><td>${e.id}</td><td>${esc(e.part)}</td><td>${esc(e.cls || e.kind)}</td>
      <td>…${esc((e.before||"").slice(-14))} <b>[${esc(e.text)}]</b> ${esc((e.after||"").slice(0,14))}…</td><td>${esc(e.reason)}</td></tr>`; });
    h += `</table><input data-job="${esc(it.id)}" placeholder="确认 3,5 / 保留 7" value="${esc(st.cleanup[it.id] ?? it.reply)}">`;
  });
  box.innerHTML = h;
  box.querySelectorAll("#bulk button").forEach(b => b.onclick = () => { const k = b.dataset.k;
    st.kinds = st.kinds.includes(k) ? st.kinds.filter(x => x != k) : st.kinds.concat([k]); save(); renderNeeded(); });
  const acc = document.getElementById("acc"); if (acc) acc.onchange = () => { st.accept = acc.checked; save(); };
  box.querySelectorAll("input[data-job]").forEach(inp => inp.onchange = () => {
    if (inp.value.trim()) st.cleanup[inp.dataset.job] = inp.value.trim(); else delete st.cleanup[inp.dataset.job]; save(); });
}
function decide(kind){
  const v = visible(); const it = v[focus]; if (!it) return;
  if (kind == "reject") { const r = prompt("Reject " + it.id + " - reason (becomes the replan note):", "");
    if (r === null) return; st.decisions[it.id] = {decision: "reject", reason: r}; }
  else if (kind == "approve") st.decisions[it.id] = {decision: "approve"};
  else delete st.decisions[it.id];
  save(); if (kind != "undo" && filt != "open") focus = Math.min(focus + 1, v.length - 1); render();
  const el = document.querySelector(".card.focus"); if (el) el.scrollIntoView({block: "nearest"});
}
function download(){
  const blob = new Blob([JSON.stringify({batch: NAME, decisions: st.decisions, cleanup: st.cleanup,
    confirm_kinds: st.kinds, accept_policy: st.accept}, null, 1)],
    {type: "application/json"});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "decisions.json"; a.click();
}
document.addEventListener("keydown", e => {
  if (e.target.tagName == "INPUT") return;
  const n = visible().length;
  if (e.key == " ") { e.preventDefault(); decide("approve"); }
  else if (e.key == "x") decide("reject"); else if (e.key == "u") decide("undo");
  else if (e.key == "d") download();
  else if (e.key == "ArrowRight" || e.key == "j") { focus = Math.min(focus + 1, n - 1); render(); }
  else if (e.key == "ArrowLeft" || e.key == "k") { focus = Math.max(focus - 1, 0); render(); }
});
document.querySelectorAll("header button[data-f]").forEach(b => b.onclick = () => {
  filt = b.dataset.f; focus = 0; document.querySelectorAll("header button[data-f]").forEach(x => x.classList.remove("on"));
  b.classList.add("on"); render(); });
document.getElementById("dl").onclick = download;
render(); renderNeeded();
</script></body></html>
"""


def generate(batch_dir):
    store = Store(batch_dir)
    try:
        name = store.spec.get("name", "batch")
        items = collect(store)
        rdir = os.path.join(store.dir, "review")
        os.makedirs(rdir, exist_ok=True)
        data = json.dumps(dict(items=items), ensure_ascii=False).replace("</", "<\\/")
        page = (PAGE.replace("__DATA__", data).replace("__NAMEJS__", json.dumps(name))
                .replace("__NAME__", html.escape(name)))
        path = os.path.join(rdir, "index.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(page)
        md, nj, ne = decisions_needed_md(items, name)
        with open(os.path.join(rdir, "decisions_needed.md"), "w", encoding="utf-8") as f:
            f.write(md)
        write_json(os.path.join(rdir, "items.json"), items)
        counts = dict(jobs=len(items), red=sum(i["qc"] == "red" for i in items),
                      sampled=sum(i["sample"] for i in items), confirm_jobs=nj, confirm_edits=ne,
                      policy=policy_totals(items),
                      caption_guesses=sum(bool(c.get("guess")) for i in items
                                          for c in (i.get("captions") or {}).get("changes") or []))
        return dict(page=path, decisions_needed=os.path.join(rdir, "decisions_needed.md"), **counts)
    finally:
        store.close()


def kind_matches(row, kinds):
    """A question row / edit matches a bulk kind: "*" / "all", its class (filler/lead), its kind (filler-merged)
    or a class prefix (filler -> filler/connector, filler/lead, ...)."""
    from vstudio import cleanup as C
    cls = row.get("cls") or C.edit_class(row)
    for k in kinds or ():
        k = str(k).strip()
        if k in ("*", "all") or k == cls or k == row.get("kind") or cls.startswith(k + "/"):
            return True
    return False


def _bulk_replies(store, d, replies, out):
    """``confirm_kinds`` / ``accept_policy`` -> extra "确认 ids" appended to the jobs' cleanup replies (in place).
    Returns {job: cleanup_view} for learning."""
    kinds, accept = d.get("confirm_kinds") or [], bool(d.get("accept_policy"))
    views = {}
    if not kinds and not accept and not replies:
        return views
    from vstudio import cleanup as C
    pol = C.load_policy()
    for j in store.jobs(REVIEW_STATES):
        jid = j["id"]
        ks = (list(kinds.get(jid) or []) + list(kinds.get("*") or [])) if isinstance(kinds, dict) else list(kinds)
        if not ks and not accept and jid not in replies:
            continue
        v = cleanup_view(store.stage_rows(jid), j["params"] or {}, pol)
        views[jid] = v
        ids = [e["id"] for e in v["confirm"] if kind_matches(e, ks)]
        pend = list((v.get("policy") or {}).get("pending") or []) if accept else []
        add = sorted(set(ids) | set(pend))
        v["policy_ids"] = set(pend) - set(ids)
        if not add:
            continue
        base = replies.get(jid, (j["params"] or {}).get("cleanup_reply") or "")
        have = C.parse_reply(base)["approve"] if base else set()
        add = [x for x in add if x not in have]
        if add:
            replies[jid] = (str(base or "") + " 确认 " + ",".join(map(str, add))).strip()
            out["bulk"][jid] = add
    return views


def _learn(store, job, reply, view, implicit=True):
    """Store the creator's answers of one job for the policy (``vstudio.cleanup.learn``). Policy approvals the
    creator merely accepted are not evidence. -> number of answers stored."""
    from vstudio import cleanup as C
    if view is None:
        view = cleanup_view(store.stage_rows(job["id"]), job["params"] or {})
    eds = view.get("edits")
    if not eds:
        return 0
    r = C.parse_reply(reply or "")
    approve = set(r["approve"]) - set(view.get("policy_ids") or ())
    try:
        C.learn(eds, approve, r["keep"], r["all_confirm"], implicit=implicit)
    except OSError:
        return 0
    asked = {e["id"] for e in eds if (e.get("base_action") or e["action"]) == "confirm"}
    return len((approve | set(r["keep"])) & asked)


def apply_decisions(batch_dir, decisions):
    """decisions: path or dict (see module doc). Returns {approved, rejected, replied, skipped, bulk: {job: ids
    added by confirm_kinds / accept_policy}, learned: answers stored for the policy}."""
    if isinstance(decisions, str) and decisions.lstrip().startswith("{"):
        decisions = json.loads(decisions)
    d = read_json(decisions) if isinstance(decisions, str) else decisions
    if d is None:
        raise ValueError(f"cannot read decisions {decisions}")
    store = Store(batch_dir)
    out = dict(approved=[], rejected=[], replied=[], skipped=[], bulk={}, learned=0)
    try:
        replies = dict(d.get("cleanup") or {})
        explicit = set(replies)
        views = _bulk_replies(store, d, replies, out)
        for jid, reply in replies.items():
            j = store.job(jid)
            if not j:
                out["skipped"].append((jid, "unknown job"))
                continue
            p = dict(j["params"] or {})
            if (p.get("cleanup_reply") or "") == (reply or ""):
                continue
            p["cleanup_reply"] = reply
            store.set_job(jid, params=p, state="planned", review=None, review_reason=None, qc=None, qc_reasons=None)
            store.log("review", f"cleanup reply: {reply}", jid)
            out["replied"].append(jid)
            out["learned"] += _learn(store, j, reply, views.get(jid), implicit=jid in explicit)
        for jid, dec in (d.get("decisions") or {}).items():
            j = store.job(jid)
            if not j:
                out["skipped"].append((jid, "unknown job"))
                continue
            if jid in out["replied"]:
                out["skipped"].append((jid, "cleanup reply given: re-run and review again"))
                continue
            kind = (dec.get("decision") if isinstance(dec, dict) else dec) or ""
            reason = dec.get("reason", "") if isinstance(dec, dict) else ""
            if kind == "approve":
                if j["state"] not in ("done", "approved", "needs-replan"):
                    out["skipped"].append((jid, f"state {j['state']} cannot be approved"))
                    continue
                store.set_job(jid, state="approved", review="approved", review_reason=None)
                out["approved"].append(jid)
            elif kind == "reject":
                store.set_job(jid, state="needs-replan", review="rejected", review_reason=reason or "rejected")
                out["rejected"].append(jid)
            else:
                out["skipped"].append((jid, f"unknown decision {kind!r}"))
                continue
            store.log("review", f"{kind}{': ' + reason if reason else ''}", jid)
        return out
    finally:
        store.close()
