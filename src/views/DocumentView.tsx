import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Archive,
  ArrowLeft,
  Check,
  Download,
  Flag,
  History,
  Minus,
  Plus,
  RotateCcw,
  ScanText,
  Send,
  Trash2,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  ApiError,
  api,
  download,
  formatBytes,
  formatDate,
  ms,
  post,
  useBlobUrl,
} from "../api";
import { useShared } from "../App";
import type { Detail, Extracted, FieldDef, PageDetail } from "../types";
import { Modal, StatusBadge, useAction, useToast } from "../ui";

type Draft = {
  values: Record<string, string>;
  flags: Record<string, string>;
  table: Record<string, string>[];
};

const draftKey = (id: string, version: number) =>
  `letranix:draft:${id}:${version}`;

function readDraft(id: string, version: number): Draft | null {
  try {
    const raw = localStorage.getItem(draftKey(id, version));
    return raw ? (JSON.parse(raw) as Draft) : null;
  } catch {
    return null;
  }
}

const SOURCE_LABEL: Record<string, string> = {
  recognized: "Read from label",
  inferred: "Inferred",
  missing: "Not found",
};

export default function DocumentView({ id }: { id: string }) {
  const { navigate, jobsTick, watchJobs, templates, settings, setDirty } =
    useShared();
  const toast = useToast();
  const { busy, run } = useAction();
  const [doc, setDoc] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"review" | "text" | "history">("review");
  const [page, setPage] = useState(1);
  const [focus, setFocus] = useState<string>("");
  const [draft, setDraft] = useState<Draft>({
    values: {},
    flags: {},
    table: [],
  });
  const [baseline, setBaseline] = useState<string>("");
  const [restored, setRestored] = useState(false);
  const [actor, setActor] = useState("");
  const [reason, setReason] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [modal, setModal] = useState<"" | "integrate" | "reopen" | "delete">(
    "",
  );
  const [confirmText, setConfirmText] = useState("");

  const load = useCallback(async () => {
    try {
      const d = await api<Detail>(`/documents/${id}`);
      setDoc(d);
      setError("");
      return d;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load, jobsTick]);

  // Initialise the editable state whenever the document version/status changes.
  const versionKey = doc ? `${doc.version}:${doc.status}` : "";
  useEffect(() => {
    if (!doc || !doc.template) return;
    const latest = doc.reviews.find((r) => r.version === doc.version);
    const base: Draft = {
      values:
        doc.status !== "needs-review" && latest
          ? latest.fields
          : Object.fromEntries(
              doc.template.fields.map((f) => [
                f.key,
                doc.fields[f.key]?.value ?? "",
              ]),
            ),
      flags: {},
      table:
        doc.status !== "needs-review" && latest?.tables.rows
          ? latest.tables.rows
          : (doc.tables.table?.rows.map((r) => r.cells) ?? []),
    };
    setBaseline(JSON.stringify(base));
    const saved =
      doc.status === "needs-review" ? readDraft(doc.id, doc.version) : null;
    setDraft(saved ?? base);
    setRestored(!!saved);
    setFieldErrors({});
    setReason("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc?.id, versionKey]);

  useEffect(() => {
    if (!actor && settings)
      setActor(String(settings.values["review.default_reviewer"]));
  }, [settings, actor]);

  const dirty =
    !!doc &&
    doc.status === "needs-review" &&
    JSON.stringify(draft) !== baseline;
  useEffect(() => {
    setDirty(dirty);
    if (!doc) return;
    try {
      if (dirty)
        localStorage.setItem(
          draftKey(doc.id, doc.version),
          JSON.stringify(draft),
        );
      else localStorage.removeItem(draftKey(doc.id, doc.version));
    } catch {
      /* storage unavailable: the in-memory draft and leave-warning still protect edits */
    }
    return () => setDirty(false);
  }, [dirty, draft, doc, setDirty]);

  if (error)
    return (
      <div className="banner error">
        {error}{" "}
        <button className="ghost" onClick={() => navigate("documents")}>
          Back to documents
        </button>
      </div>
    );
  if (!doc) return <div className="loading">Loading document…</div>;

  const template = doc.template;
  const latest = doc.reviews.find((r) => r.version === doc.version);
  const busyDoc = doc.status === "queued" || doc.status === "processing";
  const activeJob = doc.jobs.find(
    (j) => j.state === "queued" || j.state === "running",
  );
  const lastJob = doc.jobs[0];
  const outbox = latest
    ? doc.outbox.find((o) => o.review_id === latest.id)
    : undefined;
  const editing = doc.status === "needs-review";
  const setValue = (key: string, value: string) =>
    setDraft((d) => ({ ...d, values: { ...d.values, [key]: value } }));

  async function decide(decision: "approved" | "rejected") {
    setFieldErrors({});
    await run(async () => {
      try {
        const r = await post<{ rules_updated: number }>(
          `/documents/${id}/review`,
          {
            version: doc!.version,
            decision,
            actor,
            reason,
            fields: draft.values,
            issues: Object.fromEntries(
              Object.entries(draft.flags).filter(([, v]) => v !== undefined),
            ),
            table: draft.table,
          },
        );
        localStorage.removeItem(draftKey(doc!.id, doc!.version));
        setBaseline(JSON.stringify(draft));
        await load();
        toast(
          "ok",
          decision === "approved"
            ? `Review approved.${r.rules_updated ? ` ${r.rules_updated} learning rule(s) updated.` : ""} Nothing was sent to any destination.`
            : "Review rejected and recorded.",
        );
      } catch (e) {
        if (e instanceof ApiError) setFieldErrors(e.fields);
        throw e;
      }
    });
  }

  const pageCount = Math.max(doc.pages, doc.pages_detail.length, 1);
  const pageInfo = doc.pages_detail.find((p) => p.page === page);
  const focused = focus ? doc.fields[focus] : undefined;

  return (
    <div className="doc-view">
      <div className="doc-head">
        <button className="ghost" onClick={() => navigate("documents")}>
          <ArrowLeft size={16} /> Documents
        </button>
        <div className="doc-title">
          <h1>{doc.name}</h1>
          <div className="meta">
            <StatusBadge status={doc.status} />
            <span>
              {doc.mime} · {formatBytes(doc.size)} · {doc.pages} page(s) · v
              {doc.version}
            </span>
            {doc.archived ? (
              <span className="badge archived">Archived</span>
            ) : null}
          </div>
        </div>
        <div className="actions">
          {doc.version > 0 && (
            <label className="inline">
              Type
              <select
                aria-label="Document type"
                value={doc.template_id}
                disabled={busy || busyDoc}
                onChange={(e) =>
                  run(async () => {
                    if (
                      dirty &&
                      !window.confirm(
                        "Changing the type discards unsaved edits. Continue?",
                      )
                    )
                      return;
                    setDoc(
                      await post<Detail>(`/documents/${id}/template`, {
                        template_id: e.target.value,
                      }),
                    );
                  }, "Fields re-extracted with the selected type (no new OCR).")
                }
              >
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {busyDoc && activeJob ? (
            <button
              disabled={busy}
              onClick={() =>
                run(
                  () => post(`/jobs/${activeJob.id}/cancel`),
                  "Cancellation requested.",
                )
              }
            >
              <X size={15} /> Cancel processing
            </button>
          ) : (
            <button
              disabled={busy || !!doc.archived}
              className={
                doc.version === 0 || doc.status === "error" ? "primary" : ""
              }
              onClick={() =>
                run(async () => {
                  if (
                    doc.version > 0 &&
                    !window.confirm(
                      "Reprocessing runs extraction again and creates a new version that needs a new review. Continue?",
                    )
                  )
                    return;
                  await post(`/documents/${id}/process`, {});
                  watchJobs();
                  await load();
                }, "Queued for processing.")
              }
            >
              <ScanText size={15} />
              {doc.version === 0
                ? "Process"
                : doc.status === "error"
                  ? "Retry"
                  : "Reprocess"}
            </button>
          )}
          <button
            className="icon"
            title="Download original"
            aria-label="Download original"
            onClick={() =>
              run(() => download(`/documents/${id}/file`, doc.name))
            }
          >
            <Download size={16} />
          </button>
          <button
            disabled={doc.version === 0}
            title="Export document JSON (fields, provenance, OCR, reviews)"
            onClick={() =>
              run(() =>
                download(`/documents/${id}/export`, `letranix-${id}.json`),
              )
            }
          >
            Export JSON
          </button>
          <button
            disabled={busy || busyDoc}
            onClick={() =>
              run(
                async () => {
                  await post(`/documents/${id}/archive`, {
                    archived: !doc.archived,
                  });
                  await load();
                },
                doc.archived ? "Restored from archive." : "Archived.",
              )
            }
          >
            <Archive size={15} /> {doc.archived ? "Unarchive" : "Archive"}
          </button>
          {!!doc.archived && (
            <button className="danger" onClick={() => setModal("delete")}>
              <Trash2 size={15} /> Delete
            </button>
          )}
        </div>
      </div>

      {busyDoc && (
        <div className="banner info" role="status">
          {activeJob?.state === "running"
            ? `Processing page ${activeJob.progress} of ${activeJob.total || "?"}…`
            : "Waiting in the processing queue…"}
          <progress
            max={activeJob?.total || 1}
            value={activeJob?.progress || 0}
            aria-label="Processing progress"
          />
        </div>
      )}
      {doc.status === "error" && lastJob && (
        <div className="banner error" role="alert">
          <AlertTriangle size={16} /> {lastJob.error || "Processing failed."}{" "}
          Use Retry after fixing the cause (for example, OCR settings or a
          better scan).
        </div>
      )}

      <div className="doc-grid">
        <section className="viewer" aria-label="Document pages">
          <Viewer
            doc={doc}
            page={page}
            setPage={setPage}
            pageCount={pageCount}
            pageInfo={pageInfo}
            focused={focused}
            minScore={Number(settings?.values["ocr.min_line_score"] ?? 0.6)}
          />
        </section>

        <section className="side" aria-label="Review">
          <div className="tabs" role="tablist">
            {(
              [
                ["review", "Review", Check],
                ["text", "Recognised text", ScanText],
                ["history", `History (${doc.audit.length})`, History],
              ] as const
            ).map(([key, label, Icon]) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                className={tab === key ? "chosen" : ""}
                onClick={() => setTab(key)}
              >
                <Icon size={15} /> {label}
              </button>
            ))}
          </div>

          {tab === "text" && <TextPanel doc={doc} focused={focused} />}
          {tab === "history" && <HistoryPanel doc={doc} />}
          {tab === "review" &&
            (doc.version === 0 || !template ? (
              <div className="panel-body">
                <p className="muted">
                  {busyDoc
                    ? "Extraction runs in the background; this panel updates when it finishes."
                    : "Not processed yet. Text and native PDFs are read directly; images and scanned PDF pages go through local OCR."}
                </p>
              </div>
            ) : (
              <div className="panel-body review">
                {doc.classification.length > 0 && (
                  <p className="classification">
                    Type <strong>{template.name}</strong>{" "}
                    {doc.template_source === "user"
                      ? "(chosen by a reviewer)"
                      : `(classifier ${Math.round((doc.classification[0]?.probability ?? 0) * 100)}% relative likelihood)`}
                  </p>
                )}
                {restored && editing && (
                  <div className="banner info">
                    Restored unsaved edits from this device.{" "}
                    <button
                      className="ghost"
                      onClick={() => {
                        setDraft(JSON.parse(baseline));
                        setRestored(false);
                      }}
                    >
                      Discard draft
                    </button>
                  </div>
                )}
                {!editing && latest && (
                  <div className={"decision " + latest.decision}>
                    <strong>
                      {latest.decision === "approved" ? "Approved" : "Rejected"}{" "}
                      by {latest.actor}
                    </strong>{" "}
                    · {formatDate(latest.created, true)}
                    {latest.reason && <p>{latest.reason}</p>}
                  </div>
                )}
                <div className="fields">
                  {template.fields.map((f) => (
                    <FieldEditor
                      key={f.key}
                      field={f}
                      extracted={doc.fields[f.key]}
                      value={draft.values[f.key] ?? ""}
                      flag={draft.flags[f.key]}
                      errors={fieldErrors[f.key]}
                      provenance={
                        !editing ? latest?.provenance[f.key] : undefined
                      }
                      disabled={!editing || busy}
                      focused={focus === f.key}
                      onFocus={() => {
                        setFocus(f.key);
                        const p = doc.fields[f.key]?.page;
                        if (p) setPage(p);
                      }}
                      onChange={(v) => setValue(f.key, v)}
                      onFlag={(note) =>
                        setDraft((d) => {
                          const flags = { ...d.flags };
                          if (note === undefined) delete flags[f.key];
                          else flags[f.key] = note;
                          return { ...d, flags };
                        })
                      }
                    />
                  ))}
                </div>
                {template.table && (
                  <TableEditor
                    columns={template.table.columns}
                    label={template.table.label}
                    rows={draft.table}
                    disabled={!editing || busy}
                    onChange={(table) => setDraft((d) => ({ ...d, table }))}
                  />
                )}
                {!!doc.tables.pairs?.length && (
                  <details className="pairs">
                    <summary>
                      Other labelled values found ({doc.tables.pairs.length})
                    </summary>
                    <p className="muted">
                      Not part of this document type. If one belongs to a field,
                      enter it there: approval teaches LETRANIX the new label.
                    </p>
                    <dl>
                      {doc.tables.pairs.map((p, i) => (
                        <div key={i}>
                          <dt>{p.label}</dt>
                          <dd>{p.value}</dd>
                        </div>
                      ))}
                    </dl>
                  </details>
                )}

                {editing ? (
                  <div className="decide">
                    <label className="field">
                      <span>Reviewer</span>
                      <input
                        aria-label="Reviewer"
                        value={actor}
                        maxLength={80}
                        onChange={(e) => setActor(e.target.value)}
                      />
                    </label>
                    <label className="field">
                      <span>Decision note</span>
                      <textarea
                        aria-label="Decision note"
                        value={reason}
                        maxLength={1000}
                        placeholder="What did you verify or correct? Required to reject."
                        onChange={(e) => setReason(e.target.value)}
                      />
                    </label>
                    <div className="decision-actions">
                      <button
                        disabled={busy || reason.trim().length < 5}
                        onClick={() => void decide("rejected")}
                      >
                        Reject
                      </button>
                      <button
                        className="primary"
                        disabled={busy}
                        onClick={() => void decide("approved")}
                      >
                        <Check size={16} /> Approve
                      </button>
                    </div>
                    <p className="muted small">
                      {Object.keys(draft.flags).length > 0
                        ? "Flagged fields block approval until the flag is cleared; reject to record the inconsistency."
                        : "Approving records your decision. It does not send anything to a destination."}
                    </p>
                  </div>
                ) : (
                  <div className="decide">
                    {doc.status === "approved" && latest && (
                      <button
                        className="primary"
                        disabled={busy || !!outbox}
                        onClick={() => setModal("integrate")}
                      >
                        <Send size={15} />
                        {outbox
                          ? `Destination: ${outbox.state}`
                          : "Send to destination…"}
                      </button>
                    )}
                    {outbox?.state === "failed" && (
                      <p className="banner error">
                        {outbox.last_error}{" "}
                        <button
                          className="ghost"
                          onClick={() =>
                            run(async () => {
                              await post(
                                `/integrations/outbox/${outbox.id}/retry`,
                              );
                              setTimeout(load, 1500);
                            }, "Delivery retried.")
                          }
                        >
                          Retry
                        </button>
                      </p>
                    )}
                    <button disabled={busy} onClick={() => setModal("reopen")}>
                      <RotateCcw size={15} /> Reopen review
                    </button>
                  </div>
                )}
              </div>
            ))}
        </section>
      </div>

      {modal === "integrate" && latest && (
        <Modal
          title="Send approved record"
          onClose={() => setModal("")}
          footer={
            <>
              <button onClick={() => setModal("")}>Cancel</button>
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await post(`/documents/${id}/integrate`, {
                      review_id: latest.id,
                      authorize: true,
                    });
                    setModal("");
                    for (const wait of [600, 1800, 4000])
                      setTimeout(load, wait);
                  }, "Queued for delivery. Track it under Integrations.")
                }
              >
                <Send size={15} /> Authorise and send
              </button>
            </>
          }
        >
          <p>
            Destination:{" "}
            <strong>{String(settings?.values["integration.adapter"])}</strong>
            {settings?.values["integration.adapter"] === "http-demo" && (
              <> at {String(settings?.values["integration.endpoint"])}</>
            )}
            . The record is sent once; retries reuse the same idempotency key so
            the destination cannot create duplicates.
          </p>
          <dl className="kv">
            {Object.entries(latest.fields).map(([k, v]) => (
              <div key={k} className="kv-row">
                <dt>{template?.fields.find((f) => f.key === k)?.label ?? k}</dt>
                <dd>{v || <span className="muted">empty</span>}</dd>
              </div>
            ))}
          </dl>
          {(latest.tables.rows?.length ?? 0) > 0 && (
            <p className="muted">+ {latest.tables.rows!.length} table row(s)</p>
          )}
        </Modal>
      )}
      {modal === "reopen" && (
        <Modal
          title="Reopen review"
          onClose={() => setModal("")}
          footer={
            <>
              <button onClick={() => setModal("")}>Cancel</button>
              <button
                className="primary"
                disabled={busy || confirmText.trim().length < 5}
                onClick={() =>
                  run(async () => {
                    setDoc(
                      await post<Detail>(`/documents/${id}/reopen`, {
                        actor,
                        reason: confirmText,
                      }),
                    );
                    setModal("");
                    setConfirmText("");
                  }, "Review reopened. The previous decision stays in the history.")
                }
              >
                Reopen
              </button>
            </>
          }
        >
          <label className="field">
            <span>Why is this review reopened?</span>
            <textarea
              aria-label="Reason for reopening"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
            />
          </label>
        </Modal>
      )}
      {modal === "delete" && (
        <Modal
          title="Delete document permanently"
          onClose={() => setModal("")}
          footer={
            <>
              <button onClick={() => setModal("")}>Cancel</button>
              <button
                className="danger"
                disabled={busy || confirmText !== doc.name}
                onClick={() =>
                  run(async () => {
                    await post(`/documents/${id}/delete`, {
                      confirm: confirmText,
                    });
                    setModal("");
                    setDirty(false);
                    navigate("documents?archived=1");
                  }, "Document deleted. Its audit history is kept.")
                }
              >
                <Trash2 size={15} /> Delete
              </button>
            </>
          }
        >
          <p>
            The original file, extracted pages and reviews are removed. The
            audit trail keeps the event and the file's SHA-256 hash. Records
            already delivered to a destination are not affected.
          </p>
          <label className="field">
            <span>
              Type <code>{doc.name}</code> to confirm
            </span>
            <input
              aria-label="Confirm document name"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
            />
          </label>
        </Modal>
      )}
    </div>
  );
}

function Viewer({
  doc,
  page,
  setPage,
  pageCount,
  pageInfo,
  focused,
  minScore,
}: {
  doc: Detail;
  page: number;
  setPage: (n: number) => void;
  pageCount: number;
  pageInfo?: PageDetail;
  focused?: Extracted;
  minScore: number;
}) {
  const [zoom, setZoom] = useState(1);
  const [showBoxes, setShowBoxes] = useState(true);
  const isText = doc.mime === "text/plain";
  const hasImage = !isText;
  const path = hasImage
    ? `/documents/${doc.id}/pages/${page}/image?v=${doc.version}`
    : null;
  const { url, error } = useBlobUrl(path);
  const overlay = pageInfo?.has_image && pageInfo.width > 0;

  return (
    <>
      <div className="viewer-bar">
        <div className="pages-nav">
          <button
            className="icon"
            aria-label="Previous page"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
          >
            <Minus size={14} />
          </button>
          <span>
            Page {page} / {pageCount}
          </span>
          <button
            className="icon"
            aria-label="Next page"
            disabled={page >= pageCount}
            onClick={() => setPage(page + 1)}
          >
            <Plus size={14} />
          </button>
        </div>
        {pageInfo && (
          <span className="muted small">
            {pageInfo.method}
            {pageInfo.mean_score !== null &&
              ` · mean OCR score ${pageInfo.mean_score.toFixed(2)}`}
            {pageInfo.steps.length > 0 && ` · ${pageInfo.steps.join(", ")}`}
            {pageInfo.ms > 0 && ` · ${ms(pageInfo.ms)}`}
          </span>
        )}
        {hasImage && (
          <div className="zoom">
            {overlay && (
              <label className="check">
                <input
                  type="checkbox"
                  checked={showBoxes}
                  onChange={(e) => setShowBoxes(e.target.checked)}
                />
                Boxes
              </label>
            )}
            <button
              className="icon"
              aria-label="Zoom out"
              onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}
            >
              <ZoomOut size={15} />
            </button>
            <span>{Math.round(zoom * 100)}%</span>
            <button
              className="icon"
              aria-label="Zoom in"
              onClick={() => setZoom((z) => Math.min(3, z + 0.25))}
            >
              <ZoomIn size={15} />
            </button>
          </div>
        )}
      </div>
      <div className="canvas" tabIndex={0} aria-label="Page view, scrollable">
        {isText ? (
          <pre className="text-page">
            {doc.text
              ? doc.text.split("\n").map((line, i) => (
                  <span
                    key={i}
                    className={
                      focused?.evidence &&
                      line.trim() === focused.evidence.trim()
                        ? "hit"
                        : ""
                    }
                  >
                    {line + "\n"}
                  </span>
                ))
              : "Process the document to read its text."}
          </pre>
        ) : error ? (
          <p className="banner error">{error}</p>
        ) : !url ? (
          <div className="loading">Rendering page…</div>
        ) : (
          <div className="page-wrap" style={{ width: `${zoom * 100}%` }}>
            <img src={url} alt={`Page ${page} of ${doc.name}`} />
            {overlay && (
              <svg
                viewBox={`0 0 ${pageInfo!.width} ${pageInfo!.height}`}
                preserveAspectRatio="none"
                aria-hidden="true"
              >
                {showBoxes &&
                  pageInfo!.rows.flatMap((r, ri) =>
                    r.segments.map((s, si) => (
                      <rect
                        key={`${ri}-${si}`}
                        className={s.score < minScore ? "box low" : "box"}
                        x={s.bbox[0]}
                        y={s.bbox[1]}
                        width={s.bbox[2] - s.bbox[0]}
                        height={s.bbox[3] - s.bbox[1]}
                      >
                        <title>
                          {s.text} — score {s.score.toFixed(2)}
                        </title>
                      </rect>
                    )),
                  )}
                {focused?.bbox && focused.page === page && (
                  <rect
                    className="box focus"
                    x={focused.bbox[0] - 6}
                    y={focused.bbox[1] - 6}
                    width={focused.bbox[2] - focused.bbox[0] + 12}
                    height={focused.bbox[3] - focused.bbox[1] + 12}
                  />
                )}
              </svg>
            )}
          </div>
        )}
      </div>
    </>
  );
}

function FieldEditor({
  field,
  extracted,
  value,
  flag,
  errors,
  provenance,
  disabled,
  focused,
  onFocus,
  onChange,
  onFlag,
}: {
  field: FieldDef;
  extracted?: Extracted;
  value: string;
  flag?: string;
  errors?: string[];
  provenance?: string;
  disabled: boolean;
  focused: boolean;
  onFocus: () => void;
  onChange: (v: string) => void;
  onFlag: (note: string | undefined) => void;
}) {
  const changed = extracted !== undefined && value !== extracted.value;
  const id = `field-${field.key}`;
  const issues = useMemo(
    () => (changed ? [] : (extracted?.issues ?? [])),
    [changed, extracted],
  );
  return (
    <div
      className={
        "field-card" +
        (focused ? " focused" : "") +
        (issues.length || errors?.length ? " has-issue" : "") +
        (flag !== undefined ? " flagged" : "")
      }
    >
      <div className="field-top">
        <label htmlFor={id}>
          {field.label}
          {field.required && (
            <span className="req" aria-label="required">
              *
            </span>
          )}
        </label>
        <span className={"src " + (extracted?.source ?? "missing")}>
          {provenance
            ? provenance
            : changed
              ? "Edited"
              : SOURCE_LABEL[extracted?.source ?? "missing"]}
          {!changed &&
            extracted?.rule.startsWith("learned") &&
            " · learned rule"}
        </span>
      </div>
      {field.type === "enum" ? (
        <select
          id={id}
          value={value}
          disabled={disabled}
          onFocus={onFocus}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">—</option>
          {value && !field.options?.includes(value) && (
            <option value={value}>{value} (not allowed)</option>
          )}
          {field.options?.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      ) : (
        <input
          id={id}
          value={value}
          disabled={disabled}
          maxLength={1000}
          inputMode={
            field.type === "money" || field.type === "number"
              ? "decimal"
              : undefined
          }
          placeholder={field.type === "date" ? "YYYY-MM-DD" : ""}
          onFocus={onFocus}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {extracted?.evidence && (
        <button
          type="button"
          className="evidence"
          onClick={onFocus}
          disabled={false}
        >
          p.{extracted.page} · “{extracted.evidence}”
          {extracted.ocr_score !== null &&
            ` · OCR ${extracted.ocr_score.toFixed(2)}`}
        </button>
      )}
      {changed && extracted?.value && (
        <small className="muted">Extracted: {extracted.value}</small>
      )}
      {extracted?.ambiguous && !disabled && (
        <div className="candidates">
          {extracted.candidates.map((c) => (
            <button
              key={c}
              type="button"
              className="chip"
              onClick={() => onChange(c)}
            >
              {c}
            </button>
          ))}
        </div>
      )}
      {[...issues, ...(errors ?? [])].map((i) => (
        <small key={i} className="issue">
          <AlertTriangle size={12} /> {i}
        </small>
      ))}
      {!disabled &&
        (flag === undefined ? (
          <button
            type="button"
            className="ghost tiny"
            onClick={() => onFlag("")}
          >
            <Flag size={12} /> Flag inconsistency
          </button>
        ) : (
          <div className="flag-note">
            <input
              aria-label={`Inconsistency note for ${field.label}`}
              placeholder="Describe the inconsistency"
              value={flag}
              maxLength={300}
              onChange={(e) => onFlag(e.target.value)}
            />
            <button
              type="button"
              className="icon ghost"
              aria-label="Clear flag"
              onClick={() => onFlag(undefined)}
            >
              <X size={13} />
            </button>
          </div>
        ))}
    </div>
  );
}

function TableEditor({
  columns,
  label,
  rows,
  disabled,
  onChange,
}: {
  columns: FieldDef[];
  label: string;
  rows: Record<string, string>[];
  disabled: boolean;
  onChange: (rows: Record<string, string>[]) => void;
}) {
  const empty = Object.fromEntries(columns.map((c) => [c.key, ""]));
  return (
    <div className="table-editor">
      <h3>
        {label} <span className="muted">({rows.length})</span>
      </h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key}>{c.label}</th>
              ))}
              {!disabled && <th aria-label="Row actions" />}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c.key}>
                    <input
                      aria-label={`${c.label} row ${i + 1}`}
                      value={row[c.key] ?? ""}
                      disabled={disabled}
                      onChange={(e) =>
                        onChange(
                          rows.map((r, j) =>
                            j === i ? { ...r, [c.key]: e.target.value } : r,
                          ),
                        )
                      }
                    />
                  </td>
                ))}
                {!disabled && (
                  <td>
                    <button
                      className="icon ghost"
                      aria-label={`Remove row ${i + 1}`}
                      onClick={() => onChange(rows.filter((_, j) => j !== i))}
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
      {!disabled && (
        <button
          className="ghost tiny"
          onClick={() => onChange([...rows, { ...empty }])}
        >
          <Plus size={12} /> Add row
        </button>
      )}
    </div>
  );
}

function TextPanel({ doc, focused }: { doc: Detail; focused?: Extracted }) {
  if (!doc.pages_detail.length)
    return <div className="panel-body muted">No recognised text yet.</div>;
  return (
    <div className="panel-body text-panel">
      {doc.pages_detail.map((p) => (
        <section key={p.page}>
          <h3>
            Page {p.page} <small className="muted">{p.method}</small>
          </h3>
          <ol>
            {p.rows.map((r, i) => (
              <li
                key={i}
                className={
                  (focused?.page === p.page && focused?.row === i
                    ? "hit "
                    : "") + (r.score !== null && r.score < 0.6 ? "low" : "")
                }
              >
                <span>{r.text}</span>
                {r.score !== null && <small>{r.score.toFixed(2)}</small>}
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}

function HistoryPanel({ doc }: { doc: Detail }) {
  return (
    <div className="panel-body history">
      <h3>Reviews</h3>
      {doc.reviews.length === 0 && <p className="muted">No decisions yet.</p>}
      {doc.reviews.map((r) => (
        <article key={r.id} className={"decision " + r.decision}>
          <strong>
            {r.decision} · v{r.version} · {r.actor}
          </strong>{" "}
          <time>{formatDate(r.created, true)}</time>
          {r.reason && <p>{r.reason}</p>}
          <ul className="prov">
            {Object.entries(r.provenance).map(([k, v]) => (
              <li key={k}>
                <code>{k}</code> {v}
                {r.issues[k] && <em> · flagged: {r.issues[k]}</em>}
              </li>
            ))}
          </ul>
        </article>
      ))}
      <h3>Processing jobs</h3>
      <ul className="jobs">
        {doc.jobs.map((j) => (
          <li key={j.id}>
            <span className={"state " + j.state}>{j.state}</span>{" "}
            {formatDate(j.created, true)}
            {j.timings.total_ms !== undefined &&
              ` · total ${ms(j.timings.total_ms)} (OCR ${ms(j.timings.ocr_ms)}, extraction ${ms(j.timings.extract_ms)})`}
            {j.error && <div className="issue">{j.error}</div>}
          </li>
        ))}
      </ul>
      <h3>Deliveries</h3>
      {doc.outbox.length === 0 ? (
        <p className="muted">Never sent to a destination.</p>
      ) : (
        <ul className="jobs">
          {doc.outbox.map((o) => (
            <li key={o.id}>
              <span className={"state " + o.state}>{o.state}</span> {o.adapter}{" "}
              · {o.attempts} attempt(s)
              {o.last_error && <div className="issue">{o.last_error}</div>}
            </li>
          ))}
        </ul>
      )}
      <h3>Audit events</h3>
      <ul className="audit-list">
        {doc.audit.map((a) => (
          <li key={a.id}>
            <code>{a.event}</code> <span>{a.actor}</span>{" "}
            <time>{formatDate(a.created, true)}</time>
          </li>
        ))}
      </ul>
    </div>
  );
}
