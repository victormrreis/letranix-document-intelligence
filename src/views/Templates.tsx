import { useState } from "react";
import { Copy, Lock, Plus, Save, Trash2 } from "lucide-react";
import { ApiError, api, post } from "../api";
import { useShared } from "../App";
import type { FieldDef, Template } from "../types";
import { PageHeader, useAction } from "../ui";

const TYPES: FieldDef["type"][] = [
  "text",
  "identifier",
  "date",
  "number",
  "money",
  "enum",
];

const list = (s: string) =>
  s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

export default function Templates() {
  const { templates, reloadTemplates } = useShared();
  const { busy, run } = useAction();
  const [selected, setSelected] = useState<string>(templates[0]?.id ?? "");
  const [edit, setEdit] = useState<Template | null>(null);
  const [error, setError] = useState("");
  const current = edit ?? templates.find((t) => t.id === selected) ?? null;
  const readOnly = !edit;

  const startCopy = (t: Template) => {
    setError("");
    setEdit({
      ...structuredClone(t),
      id: t.builtin ? `${t.id}-custom` : t.id,
      name: t.builtin ? `${t.name} (custom)` : t.name,
      builtin: false,
    });
  };
  const update = (patch: Partial<Template>) =>
    setEdit((e) => (e ? { ...e, ...patch } : e));
  const updateField = (i: number, patch: Partial<FieldDef>) =>
    setEdit((e) =>
      e
        ? {
            ...e,
            fields: e.fields.map((f, j) => (j === i ? { ...f, ...patch } : f)),
          }
        : e,
    );

  return (
    <>
      <PageHeader
        title="Document types"
        subtitle="Templates define the fields LETRANIX looks for, the labels that introduce them and how values are validated. Built-in types are read-only; copy one to customise it."
        actions={
          <button
            className="primary"
            onClick={() =>
              setEdit({
                id: "new-type",
                name: "New document type",
                description: "",
                keywords: [],
                fields: [
                  {
                    key: "reference",
                    label: "Reference",
                    type: "identifier",
                    labels: ["reference"],
                    required: true,
                  },
                ],
              })
            }
          >
            <Plus size={16} /> New type
          </button>
        }
      />
      <div className="split">
        <ul className="side-list" aria-label="Document types">
          {templates.map((t) => (
            <li key={t.id}>
              <button
                className={selected === t.id && !edit ? "active" : ""}
                onClick={() => {
                  setEdit(null);
                  setSelected(t.id);
                }}
              >
                {t.builtin && <Lock size={13} aria-label="built-in" />} {t.name}
                <small>{t.fields.length} fields</small>
              </button>
            </li>
          ))}
        </ul>
        {current && (
          <section className="panel template-editor">
            <div className="panel-head">
              <h2>{readOnly ? current.name : "Edit type"}</h2>
              <div className="actions">
                {readOnly ? (
                  <>
                    <button onClick={() => startCopy(current)}>
                      <Copy size={15} />{" "}
                      {current.builtin ? "Copy to customise" : "Edit"}
                    </button>
                    {!current.builtin && (
                      <button
                        className="danger"
                        disabled={busy}
                        onClick={() =>
                          window.confirm(`Delete type ${current.name}?`) &&
                          run(async () => {
                            await api(`/templates/${current.id}`, {
                              method: "DELETE",
                            });
                            await reloadTemplates();
                            setSelected(templates[0]?.id ?? "");
                          }, "Type deleted.")
                        }
                      >
                        <Trash2 size={15} /> Delete
                      </button>
                    )}
                  </>
                ) : (
                  <>
                    <button onClick={() => setEdit(null)}>Cancel</button>
                    <button
                      className="primary"
                      disabled={busy}
                      onClick={() =>
                        run(async () => {
                          setError("");
                          try {
                            const { builtin: _b, ...body } = edit!;
                            void _b;
                            const saved = await post<Template>(
                              "/templates",
                              body,
                            );
                            await reloadTemplates();
                            setEdit(null);
                            setSelected(saved.id);
                          } catch (e) {
                            if (e instanceof ApiError) setError(e.message);
                            throw e;
                          }
                        }, "Type saved.")
                      }
                    >
                      <Save size={15} /> Save
                    </button>
                  </>
                )}
              </div>
            </div>
            {error && <p className="banner error">{error}</p>}
            <div className="form-grid">
              <label className="field">
                <span>Identifier</span>
                <input
                  value={current.id}
                  disabled={readOnly}
                  onChange={(e) => update({ id: e.target.value })}
                />
              </label>
              <label className="field">
                <span>Name</span>
                <input
                  value={current.name}
                  disabled={readOnly}
                  onChange={(e) => update({ name: e.target.value })}
                />
              </label>
              <label className="field wide">
                <span>Classification keywords (comma separated)</span>
                <input
                  value={current.keywords.join(", ")}
                  disabled={readOnly}
                  onChange={(e) => update({ keywords: list(e.target.value) })}
                />
              </label>
            </div>
            <div className="table-wrap">
              <table className="fields-table">
                <thead>
                  <tr>
                    <th>Key</th>
                    <th>Label</th>
                    <th>Type</th>
                    <th>Labels in documents</th>
                    <th>Format (regex) / options</th>
                    <th>Required</th>
                    {!readOnly && <th aria-label="Remove" />}
                  </tr>
                </thead>
                <tbody>
                  {current.fields.map((f, i) => (
                    <tr key={i}>
                      <td>
                        <input
                          aria-label="Field key"
                          value={f.key}
                          disabled={readOnly}
                          onChange={(e) =>
                            updateField(i, { key: e.target.value })
                          }
                        />
                      </td>
                      <td>
                        <input
                          aria-label="Field label"
                          value={f.label}
                          disabled={readOnly}
                          onChange={(e) =>
                            updateField(i, { label: e.target.value })
                          }
                        />
                      </td>
                      <td>
                        <select
                          aria-label="Field type"
                          value={f.type}
                          disabled={readOnly}
                          onChange={(e) =>
                            updateField(i, {
                              type: e.target.value as FieldDef["type"],
                            })
                          }
                        >
                          {TYPES.map((t) => (
                            <option key={t}>{t}</option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <input
                          aria-label="Labels"
                          value={f.labels.join(", ")}
                          disabled={readOnly}
                          onChange={(e) =>
                            updateField(i, { labels: list(e.target.value) })
                          }
                        />
                      </td>
                      <td>
                        {f.type === "enum" ? (
                          <input
                            aria-label="Options"
                            value={(f.options ?? []).join(", ")}
                            disabled={readOnly}
                            onChange={(e) =>
                              updateField(i, { options: list(e.target.value) })
                            }
                          />
                        ) : (
                          <input
                            aria-label="Pattern"
                            value={f.pattern ?? ""}
                            disabled={readOnly}
                            placeholder="optional"
                            onChange={(e) =>
                              updateField(i, {
                                pattern: e.target.value || undefined,
                              })
                            }
                          />
                        )}
                      </td>
                      <td>
                        <input
                          type="checkbox"
                          aria-label="Required"
                          checked={f.required}
                          disabled={readOnly}
                          onChange={(e) =>
                            updateField(i, { required: e.target.checked })
                          }
                        />
                      </td>
                      {!readOnly && (
                        <td>
                          <button
                            className="icon ghost"
                            aria-label="Remove field"
                            onClick={() =>
                              update({
                                fields: current.fields.filter(
                                  (_, j) => j !== i,
                                ),
                              })
                            }
                          >
                            <Trash2 size={13} />
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!readOnly && (
              <button
                className="ghost"
                onClick={() =>
                  update({
                    fields: [
                      ...current.fields,
                      {
                        key: `field_${current.fields.length + 1}`,
                        label: "New field",
                        type: "text",
                        labels: ["new field"],
                        required: false,
                      },
                    ],
                  })
                }
              >
                <Plus size={14} /> Add field
              </button>
            )}
            {current.table && (
              <p className="muted">
                Line-item table “{current.table.label}” with columns{" "}
                {current.table.columns.map((c) => c.label).join(", ")}.
              </p>
            )}
          </section>
        )}
      </div>
    </>
  );
}
