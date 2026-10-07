// Opt-in anonymous usage counts (main/usage.ts): the first-run card, the Settings › General › Privacy group and
// the one-time ask shown to profiles made before the choice existed. Default OFF: unset = never asked = off.
import { useEffect, useState } from "react";
import type { SettingsMsg, UsageStatusMsg } from "../../../shared/deskApi";
import { getLang, t } from "../i18n";
import { Group, Row, Toggle } from "../settings/kit";
import { CAPS } from "../../../shared/edition";

/** the docs page "Privacy: what Reelfold sends", in the UI language */
export function usageDocsUrl(): string {
  const l = getLang();
  const p = l === "zh-CN" ? "zh/" : l === "fr" ? "fr/" : "";
  return `https://reelfold.com/docs/${p}concepts/usage-counts/`;
}

function DocsLink() {
  return (
    <button
      type="button"
      className="s2-link"
      onClick={() => void window.desk.openExternal(usageDocsUrl())}
      data-testid="usage-docs"
    >
      {t("usage.link")}
    </button>
  );
}

/** First run: a plain checkbox, unchecked. Saved at once (it survives a skip, a reload and a restart). */
export function UsageFirstRunCard({ settings }: { settings: SettingsMsg }) {
  const [on, setOn] = useState(settings.usagePings === "on");
  // the Lite (Mac App Store) build sends no usage counts at all ("Data Not Collected"): nothing to ask
  if (!CAPS.usageCounts) return null;
  return (
    <div
      className="card col fr-usage"
      data-testid="fr-usage"
      style={{ gap: 6 }}
    >
      <label
        className="row"
        style={{ gap: 8, alignItems: "flex-start", cursor: "pointer" }}
      >
        <input
          type="checkbox"
          checked={on}
          onChange={(e) => {
            setOn(e.target.checked);
            void window.desk.setSettings({
              usagePings: e.target.checked ? "on" : "off",
            });
          }}
          data-testid="fr-usage-toggle"
          style={{ marginTop: 3 }}
        />
        <span className="col" style={{ gap: 2 }}>
          <b style={{ fontWeight: 500 }}>{t("usage.toggle")}</b>
          <span className="muted small">
            {t("usage.what")} <DocsLink />
          </span>
        </span>
      </label>
    </div>
  );
}

type UsageGroupProps = {
  settings: SettingsMsg;
  save: (patch: { usagePings: "on" | "off" }) => Promise<unknown>;
};

/** Settings › General › Privacy (absent in the Lite build, which sends nothing) */
export function UsageSettingsGroup(props: UsageGroupProps) {
  return CAPS.usageCounts ? <UsageGroup {...props} /> : null;
}

function UsageGroup({ settings, save }: UsageGroupProps) {
  const [st, setSt] = useState<UsageStatusMsg | null>(null);
  const [msg, setMsg] = useState<{ text: string; error?: boolean } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const on = settings.usagePings === "on";
  useEffect(() => {
    void window.desk.usage
      ?.status()
      .then(setSt)
      .catch(() => undefined);
  }, [on]);
  return (
    <Group title={t("usage.title")} testId="settings-usage">
      <Row
        label={t("usage.toggle")}
        hint={
          <>
            {t("usage.what")} <DocsLink />
            {st && !st.allowed && (
              <span
                style={{ display: "block", marginTop: 4 }}
                data-testid="usage-dev-off"
              >
                {t("usage.devOff")}
              </span>
            )}
          </>
        }
      >
        <Toggle
          checked={on}
          onChange={(v) => void save({ usagePings: v ? "on" : "off" })}
          label={t("usage.toggle")}
          testId="usage-toggle"
        />
      </Row>
      {/* the id and its actions exist only once sharing was turned on (no id is made before) */}
      {st?.installId && (
        <Row
          label={t("usage.id")}
          hint={t("usage.idHint")}
          testId="usage-id-row"
        >
          <code
            className="s2-val"
            data-testid="usage-id"
            style={{ userSelect: "all", fontSize: 12 }}
          >
            {st.installId}
          </code>
          <button
            className="s2-link"
            onClick={() => void window.desk.usage.resetId().then(setSt)}
            data-testid="usage-reset"
          >
            {t("usage.reset")}
          </button>
        </Row>
      )}
      {(st?.installId || msg) && (
        <Row
          label={t("usage.delete")}
          hint={
            msg ? (
              <span
                className={msg.error ? "err" : ""}
                data-testid="usage-delete-msg"
              >
                {msg.text}
              </span>
            ) : (
              t("usage.deleteHint")
            )
          }
        >
          <button
            className="btn sm"
            disabled={busy || !st?.installId}
            onClick={async () => {
              setBusy(true);
              setMsg(null);
              try {
                const r = await window.desk.usage.deleteData();
                setSt(r.status);
                setMsg(
                  r.ok
                    ? { text: t("usage.deleted", { n: r.deleted ?? 0 }) }
                    : {
                        text: t("usage.deleteFailed", {
                          error: r.error ?? "?",
                        }),
                        error: true,
                      },
                );
              } finally {
                setBusy(false);
              }
            }}
            data-testid="usage-delete"
          >
            {t("usage.delete")}
          </button>
        </Row>
      )}
    </Group>
  );
}

/** One-time, non-blocking ask for an installed app whose profile predates the choice. Either button records it. */
export function UsageAsk() {
  return CAPS.usageCounts ? <UsageAskCard /> : null;
}

function UsageAskCard() {
  const [s, setS] = useState<SettingsMsg | null>(null);
  useEffect(() => {
    void window.desk
      .getSettings()
      .then(setS)
      .catch(() => undefined);
  }, []);
  if (!s || !s.packaged || !s.firstRunDone || s.usagePings !== undefined)
    return null;
  const choose = (v: "on" | "off") =>
    void window.desk.setSettings({ usagePings: v }).then(setS);
  return (
    <div
      className="banner"
      data-testid="usage-ask"
      role="region"
      aria-label={t("usage.ask.title")}
    >
      <div className="sp">
        <b>{t("usage.ask.title")}</b>
        <span className="muted">
          {t("usage.what")} <DocsLink />
        </span>
      </div>
      <button
        className="btn"
        onClick={() => choose("off")}
        data-testid="usage-ask-no"
      >
        {t("usage.ask.no")}
      </button>
      <button
        className="btn primary"
        onClick={() => choose("on")}
        data-testid="usage-ask-yes"
      >
        {t("usage.ask.yes")}
      </button>
    </div>
  );
}
