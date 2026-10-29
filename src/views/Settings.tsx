import { useEffect, useState } from "react";
import { DatabaseBackup, Download, RotateCcw, Save } from "lucide-react";
import { api, download, formatBytes, formatDate, post } from "../api";
import { useShared } from "../App";
import type { SettingSpec } from "../types";
import { Modal, PageHeader, useAction, useToast } from "../ui";

const GROUPS: [string, string][] = [
  ["processing", "Processing"],
  ["ocr", "OCR and preprocessing"],
  ["review", "Review"],
  ["learning", "Learning"],
  ["integration", "Integration"],
  ["interface", "Interface"],
];

type Value = string | number | boolean;
type Backup = { name: string; bytes: number; created: string };

export default function Settings() {
  const { settings, reloadSettings } = useShared();
  const toast = useToast();
  const { busy, run } = useAction();
  const [values, setValues] = useState<Record<string, Value>>({});
  const [backups, setBackups] = useState<Backup[]>([]);
  const [restore, setRestore] = useState<Backup | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (settings) setValues(settings.values);
  }, [settings]);
  useEffect(() => {
    api<Backup[]>("/backups")
      .then(setBackups)
      .catch(() => {});
  }, [tick]);

  if (!settings) return <div className="loading">Loading settings…</div>;
  const changed = Object.fromEntries(
    Object.entries(values).filter(([k, v]) => settings.values[k] !== v),
  );

  const input = (s: SettingSpec) => {
    const v = values[s.key];
    const set = (nv: Value) => setValues((x) => ({ ...x, [s.key]: nv }));
    if (s.kind === "bool")
      return (
        <input
          type="checkbox"
          id={s.key}
          checked={Boolean(v)}
          onChange={(e) => set(e.target.checked)}
        />
      );
    if (s.kind === "choice")
      return (
        <select
          id={s.key}
          value={String(v)}
          onChange={(e) => set(e.target.value)}
        >
          {s.choices.map((c) => (
            <option
              key={c}
              value={c}
              disabled={c in settings.engines && !settings.engines[c]}
            >
              {c}
              {c in settings.engines && !settings.engines[c]
                ? " (not installed)"
                : ""}
            </option>
          ))}
        </select>
      );
    if (s.kind === "int" || s.kind === "float")
      return (
        <input
          id={s.key}
          type="number"
          min={s.minimum ?? undefined}
          max={s.maximum ?? undefined}
          step={s.kind === "float" ? 0.05 : 1}
          value={String(v)}
          onChange={(e) =>
            set(e.target.value === "" ? "" : Number(e.target.value))
          }
        />
      );
    return (
      <input
        id={s.key}
        value={String(v ?? "")}
        placeholder={s.kind === "directory" ? "C:\\path\\to\\inbox" : ""}
        onChange={(e) => set(e.target.value)}
      />
    );
  };

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="Saved in the workspace database and applied to the next operation. Every value is validated by the service; limits cannot be removed."
        actions={
          <>
            <button
              disabled={!Object.keys(changed).length}
              onClick={() => setValues(settings.values)}
            >
              Discard
            </button>
            <button
              className="primary"
              disabled={busy || !Object.keys(changed).length}
              onClick={() =>
                run(
                  async () => {
                    await api("/settings", {
                      method: "PATCH",
                      body: JSON.stringify(changed),
                    });
                    await reloadSettings();
                  },
                  `${Object.keys(changed).length} setting(s) saved.`,
                )
              }
            >
              <Save size={15} /> Save changes
            </button>
          </>
        }
      />
      <div className="settings-grid">
        {GROUPS.map(([group, title]) => (
          <section key={group} className="panel">
            <h2>{title}</h2>
            {settings.schema
              .filter((s) => s.group === group)
              .map((s) => (
                <div
                  key={s.key}
                  className={"setting" + (s.key in changed ? " changed" : "")}
                >
                  <label htmlFor={s.key}>
                    {s.label}
                    {s.minimum !== null && s.kind !== "bool" && (
                      <small className="muted">
                        {" "}
                        ({s.minimum}–{s.maximum})
                      </small>
                    )}
                  </label>
                  {input(s)}
                  {s.help && <small className="muted">{s.help}</small>}
                </div>
              ))}
          </section>
        ))}
        <section className="panel">
          <h2>
            <DatabaseBackup size={18} /> Backup and restore
          </h2>
          <p className="muted small">
            Workspace <code>{settings.workspace}</code> · database schema v
            {settings.schema_version}. A backup contains the database and stored
            originals; restoring first takes a safety backup.
          </p>
          <button
            className="primary"
            disabled={busy}
            onClick={() =>
              run(async () => {
                await post("/backups");
                setTick((t) => t + 1);
              }, "Backup created.")
            }
          >
            Create backup
          </button>
          <ul className="backups">
            {backups.map((b) => (
              <li key={b.name}>
                <span>
                  {b.name}
                  <small className="muted">
                    {formatBytes(b.bytes)} · {formatDate(b.created, true)}
                  </small>
                </span>
                <button
                  className="icon"
                  aria-label={`Download ${b.name}`}
                  onClick={() =>
                    run(() => download(`/backups/${b.name}`, b.name))
                  }
                >
                  <Download size={14} />
                </button>
                <button onClick={() => setRestore(b)}>
                  <RotateCcw size={14} /> Restore
                </button>
              </li>
            ))}
          </ul>
        </section>
      </div>
      {restore && (
        <Modal
          title="Restore backup"
          onClose={() => setRestore(null)}
          footer={
            <>
              <button onClick={() => setRestore(null)}>Cancel</button>
              <button
                className="danger"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    const r = await post<{ safety_backup: string }>(
                      `/backups/${restore.name}/restore`,
                    );
                    setRestore(null);
                    setTick((t) => t + 1);
                    await reloadSettings();
                    toast(
                      "info",
                      `Safety backup ${r.safety_backup} was taken first.`,
                    );
                  }, "Workspace restored.")
                }
              >
                Restore
              </button>
            </>
          }
        >
          <p>
            Replace the current workspace with <strong>{restore.name}</strong>?
            Processing and deliveries pause while restoring. A safety backup of
            the current state is created first, so this can be undone.
          </p>
        </Modal>
      )}
    </>
  );
}
