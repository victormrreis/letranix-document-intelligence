import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowRight,
  Check,
  CircleDot,
  FileText,
  FolderOpen,
  History,
  Layers3,
  LoaderCircle,
  Search,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import "./style.css";

type FieldValue = {
  value: string;
  evidence: string;
  ambiguous: boolean;
  confidence: null;
};
type Summary = {
  id: string;
  name: string;
  status: string;
  created: string;
  mime: string;
  version: number;
  method: string;
};
type Review = {
  id: string;
  decision: string;
  actor: string;
  reason: string;
  fields: string;
  version: number;
};
type Detail = Summary & {
  text: string;
  fields: Record<string, FieldValue>;
  reviews: Review[];
  audit: { id: number; event: string; actor: string; created: string }[];
  jobs: { id: string; state: string; error: string }[];
  integrations: { id: string; review_id: string; payload: string }[];
};
const keys = ["reference", "organization", "category", "date", "description"];
const categories = [
  "service-order",
  "operational-report",
  "administrative-request",
  "handwritten-form",
];
let token = "";
async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!token) {
    const session = await fetch("/api/session", {
      headers: { "X-Letranix-Client": "browser" },
    });
    if (!session.ok) throw new Error("Cannot start local session");
    token = (await session.json()).token;
  }
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const r = await fetch("/api" + path, { ...init, headers });
  if (!r.ok) {
    const error = await r.json();
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : "Check the submitted fields",
    );
  }
  if (path.endsWith("/file")) return (await r.blob()) as T;
  return r.json();
}
function App() {
  const [items, setItems] = useState<Summary[]>([]),
    [doc, setDoc] = useState<Detail | null>(null);
  const [query, setQuery] = useState(""),
    [status, setStatus] = useState(""),
    [category, setCategory] = useState("");
  const [tab, setTab] = useState<"review" | "history">("review"),
    [values, setValues] = useState<Record<string, string>>({});
  const [actor, setActor] = useState("Demo Reviewer"),
    [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [preview, setPreview] = useState(""),
    [integrating, setIntegrating] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  async function refresh() {
    setItems(
      await api<Summary[]>(
        `/documents?q=${encodeURIComponent(query)}&status=${status}&category=${category}`,
      ),
    );
  }
  async function select(id: string) {
    const d = await api<Detail>(`/documents/${id}`);
    setDoc(d);
    setReason("");
    setIntegrating(false);
    const approved = d.reviews.findLast(
      (r) => r.version === d.version && r.decision === "approved",
    );
    setValues(
      approved
        ? JSON.parse(approved.fields)
        : Object.fromEntries(keys.map((k) => [k, d.fields[k]?.value ?? ""])),
    );
  }
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unexpected local error");
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    let active = true;
    const timer = setTimeout(() => {
      api<Summary[]>(
        `/documents?q=${encodeURIComponent(query)}&status=${status}&category=${category}`,
      )
        .then((d) => {
          if (active) setItems(d);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    }, 180);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [query, status, category]);
  useEffect(() => {
    let active = true;
    let url = "";
    setPreview("");
    if (doc)
      api<Blob>(`/documents/${doc.id}/file`)
        .then((b) => {
          url = URL.createObjectURL(b);
          if (active) setPreview(url);
        })
        .catch((e) => setError(e.message));
    return () => {
      active = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [doc?.id]);
  async function upload(files: FileList | null) {
    if (!files) return;
    await run(async () => {
      let last = "";
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        const r = await api<{ id: string; duplicate: boolean }>("/documents", {
          method: "POST",
          body: form,
        });
        last = r.id;
        setNotice(
          r.duplicate
            ? "Identical document already in library."
            : "Document imported. Process it to extract fields.",
        );
      }
      await refresh();
      if (last) await select(last);
    });
    if (fileInput.current) fileInput.current.value = "";
  }
  async function process() {
    if (!doc) return;
    await run(async () => {
      await api(`/documents/${doc.id}/process`, { method: "POST" });
      await select(doc.id);
      await refresh();
      setNotice("Extraction complete. Review every field against the source.");
    });
  }
  async function decide(decision: string) {
    if (!doc) return;
    await run(async () => {
      await api(`/documents/${doc.id}/review`, {
        method: "POST",
        body: JSON.stringify({
          version: doc.version,
          decision,
          actor,
          reason,
          fields: values,
        }),
      });
      await select(doc.id);
      await refresh();
      setNotice("Review saved. No integration was executed.");
    });
  }
  const currentReview = doc?.reviews.findLast(
    (r) => r.version === doc.version && r.decision === "approved",
  );
  const currentIntegrated =
    doc?.integrations.some((i) => i.review_id === currentReview?.id) ?? false;
  const stats = {
    total: items.length,
    review: items.filter((i) => i.status === "needs-review").length,
    approved: items.filter((i) => i.status === "approved").length,
  };
  return (
    <div className="app">
      <aside className="sidebar">
        <a className="brand" href="/">
          <img src="/mark.svg" alt="" />
          <span>
            LETRANIX<small>DOCUMENT INTELLIGENCE</small>
          </span>
        </a>
        <span className="nav-label">WORKSPACE</span>
        <button className="nav active" onClick={() => setDoc(null)}>
          <FolderOpen size={19} />
          Document library<span>{stats.total}</span>
        </button>
        <div className="nav muted">
          <Layers3 size={19} />
          Local demo workspace
        </div>
        <div className="sidebar-bottom">
          <ShieldCheck size={22} />
          <strong>Your documents stay here.</strong>
          <p>
            Local processing. Human decisions.
            <br />
            No external integrations configured.
          </p>
          <span className="version">EVALUATION · v0.1.0</span>
        </div>
      </aside>
      <main>
        <header>
          <div className="breadcrumbs">
            Workspace <span>/</span> Document library
          </div>
          <div className="local">
            <i /> LOCAL-FIRST
          </div>
        </header>
        <section className="heading">
          <div>
            <div className="eyebrow">FROM DOCUMENT TO DECISION</div>
            <h1>
              Document intelligence<span>.</span>
            </h1>
            <p>Do documento bruto ao dado confiável.</p>
          </div>
          <button
            className="primary"
            disabled={busy}
            onClick={() => fileInput.current?.click()}
          >
            <Upload size={17} />
            Import documents
          </button>
          <input
            ref={fileInput}
            type="file"
            accept=".txt,.pdf,.png,.jpg,.jpeg"
            multiple
            hidden
            onChange={(e) => void upload(e.target.files)}
          />
        </section>
        <div className="metrics">
          <div>
            <FileText />
            <span>
              Documents in view
              <strong>{stats.total.toString().padStart(2, "0")}</strong>
            </span>
          </div>
          <div>
            <CircleDot />
            <span>
              Awaiting human review
              <strong>{stats.review.toString().padStart(2, "0")}</strong>
            </span>
          </div>
          <div>
            <ShieldCheck />
            <span>
              Approved in view
              <strong>{stats.approved.toString().padStart(2, "0")}</strong>
            </span>
          </div>
          <div className="principle">
            <span className="pill">HUMAN IN THE LOOP</span>
            <p>
              Extraction suggests.
              <br />
              <strong>You make the decision.</strong>
            </p>
          </div>
        </div>
        {error && (
          <div className="alert error" role="alert">
            {error}
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              <X size={16} />
            </button>
          </div>
        )}
        {notice && (
          <div className="alert" role="status">
            {notice}
          </div>
        )}
        <div className="workspace">
          <section className="library">
            <div className="section-title">
              <h2>Document library</h2>
              <span className="dim">{items.length} in view · max 500</span>
            </div>
            <div className="filters">
              <label className="search">
                <Search size={17} />
                <input
                  aria-label="Search documents"
                  placeholder="Search documents or extracted text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </label>
              <select
                aria-label="Filter status"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                <option value="">All statuses</option>
                {[
                  "imported",
                  "needs-review",
                  "approved",
                  "rejected",
                  "error",
                ].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
              <select
                aria-label="Filter category"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="">All categories</option>
                {categories.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </div>
            <div className="document-list">
              {items.length === 0 ? (
                <div className="empty">
                  <FolderOpen size={30} />
                  <h3>No documents in this view</h3>
                  <p>
                    Import a synthetic text, image or native-text PDF.
                    <br />
                    Maximum 10 MiB per document.
                  </p>
                </div>
              ) : (
                items.map((i) => (
                  <button
                    disabled={busy}
                    className={
                      "document " + (doc?.id === i.id ? "selected" : "")
                    }
                    key={i.id}
                    onClick={() => void run(() => select(i.id))}
                  >
                    <span className="file-icon">
                      <FileText size={21} />
                    </span>
                    <span className="doc-name">
                      {i.name}
                      <small>
                        {i.mime.split("/")[1].toUpperCase()} ·{" "}
                        {new Date(i.created).toLocaleDateString()} · v
                        {i.version}
                      </small>
                    </span>
                    <span className={"badge " + i.status}>
                      {i.status.replaceAll("-", " ")}
                    </span>
                    <ArrowRight size={16} />
                  </button>
                ))
              )}
            </div>
            <div className="library-foot">
              <ShieldCheck size={14} />
              Synthetic examples only for portfolio evaluation.
            </div>
          </section>
          {!doc ? (
            <section className="welcome">
              <div className="orbit">
                <FileText size={36} />
              </div>
              <span className="eyebrow">A TRACEABLE WORKFLOW</span>
              <h2>
                Raw input.
                <br />
                Reviewed output.
              </h2>
              <p>
                Select a document to inspect its source,
                <br />
                extract structured fields and record a decision.
              </p>
              <ol>
                <li>Import & process</li>
                <li>Review the evidence</li>
                <li>Approve, then integrate explicitly</li>
              </ol>
              <span className="dim">
                No field accuracy scores are invented.
              </span>
            </section>
          ) : (
            <section className="detail" aria-label="Document workspace">
              <div className="detail-head">
                <div>
                  <span className="eyebrow">DOCUMENT WORKSPACE</span>
                  <h2>{doc.name}</h2>
                  <span className={"badge " + doc.status}>{doc.status}</span>
                </div>
                <button
                  aria-label="Close document"
                  onClick={() => setDoc(null)}
                >
                  <X size={19} />
                </button>
              </div>
              <div className="tabs">
                <button
                  className={tab === "review" ? "chosen" : ""}
                  onClick={() => setTab("review")}
                >
                  <FileText size={15} />
                  Source & review
                </button>
                <button
                  className={tab === "history" ? "chosen" : ""}
                  onClick={() => setTab("history")}
                >
                  <History size={15} />
                  Audit trail ({doc.audit.length})
                </button>
              </div>
              {tab === "history" ? (
                <div className="timeline">
                  {doc.audit.map((a) => (
                    <article key={a.id}>
                      <i />
                      <strong>{a.event}</strong>
                      <p>
                        {a.actor} · {new Date(a.created).toLocaleString()}
                      </p>
                    </article>
                  ))}
                  <h3>Processing jobs</h3>
                  {doc.jobs.map((j) => (
                    <p key={j.id}>
                      {j.state}
                      {j.error && " · " + j.error}
                    </p>
                  ))}
                  <h3>Review decisions</h3>
                  {doc.reviews.map((r) => (
                    <article key={r.id}>
                      <strong>
                        {r.decision} · v{r.version} · {r.actor}
                      </strong>
                      <p>{r.reason}</p>
                      <pre>{JSON.stringify(JSON.parse(r.fields), null, 2)}</pre>
                    </article>
                  ))}
                  <h3>Local demo records</h3>
                  <p>
                    {doc.integrations.length} integration(s) stored in this
                    workspace.
                  </p>
                </div>
              ) : (
                <>
                  <div className="source">
                    <div className="source-label">
                      SOURCE DOCUMENT{" "}
                      <span>{doc.method || "Not processed"}</span>
                    </div>
                    {doc.mime.startsWith("image/") && preview ? (
                      <img src={preview} alt="Uploaded document source" />
                    ) : doc.mime === "application/pdf" && preview ? (
                      <iframe title="PDF source document" src={preview} />
                    ) : (
                      <pre>
                        {doc.text ||
                          "Process this document to see extracted text. The original file is available below."}
                      </pre>
                    )}
                    {preview && (
                      <a href={preview} download={doc.name}>
                        Download original
                      </a>
                    )}
                  </div>
                  {doc.status === "imported" || doc.status === "error" ? (
                    <div className="review-intro">
                      <h3>Ready for local processing</h3>
                      <p>
                        Text and native PDF extraction are built in. PNG/JPEG
                        use the optional local OCR engine.
                      </p>
                      <button
                        className="primary"
                        disabled={busy}
                        onClick={() => void process()}
                      >
                        {busy ? (
                          <LoaderCircle className="spin" size={16} />
                        ) : (
                          <Layers3 size={16} />
                        )}
                        Process document
                      </button>
                    </div>
                  ) : (
                    <div className="review-form">
                      <div className="section-title">
                        <h3>Structured fields</h3>
                        <span className="pill">v{doc.version}</span>
                      </div>
                      <p className="dim">
                        Compare each field with the source. Corrections are
                        stored separately from extraction.
                      </p>
                      {keys.map((k) => (
                        <label className="field" key={k}>
                          <span>
                            {k}
                            {doc.fields[k]?.ambiguous && (
                              <b className="warning">
                                Multiple values · verify
                              </b>
                            )}
                          </span>
                          {k === "category" ? (
                            <select
                              aria-label={k}
                              disabled={doc.status !== "needs-review" || busy}
                              value={values[k] || ""}
                              onChange={(e) =>
                                setValues({ ...values, [k]: e.target.value })
                              }
                            >
                              <option value="">Select category</option>
                              {categories.map((c) => (
                                <option key={c}>{c}</option>
                              ))}
                            </select>
                          ) : (
                            <input
                              aria-label={k}
                              type={k === "date" ? "date" : "text"}
                              maxLength={1000}
                              disabled={doc.status !== "needs-review" || busy}
                              value={values[k] || ""}
                              onChange={(e) =>
                                setValues({ ...values, [k]: e.target.value })
                              }
                            />
                          )}
                          <small>
                            Extracted: {doc.fields[k]?.value || "Missing"}
                            {values[k] !== doc.fields[k]?.value && (
                              <b className="corrected"> · manually changed</b>
                            )}
                          </small>
                          <small className="evidence">
                            {doc.fields[k]?.evidence ||
                              "No labeled source evidence"}
                          </small>
                        </label>
                      ))}
                      {doc.status === "needs-review" ? (
                        <>
                          <label className="field">
                            Reviewer
                            <input
                              aria-label="Reviewer"
                              value={actor}
                              maxLength={80}
                              onChange={(e) => setActor(e.target.value)}
                            />
                          </label>
                          <label className="field">
                            Decision reason
                            <textarea
                              aria-label="Decision reason"
                              value={reason}
                              maxLength={1000}
                              onChange={(e) => setReason(e.target.value)}
                              placeholder="Explain your verification or corrections (at least 5 characters)"
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
                              disabled={
                                busy ||
                                reason.trim().length < 5 ||
                                keys.some((k) => !values[k]?.trim())
                              }
                              onClick={() => void decide("approved")}
                            >
                              <Check size={16} />
                              Approve review
                            </button>
                          </div>
                          <p className="dim">
                            Approval saves a human decision. It does not execute
                            any integration.
                          </p>
                        </>
                      ) : (
                        <>
                          <p className="alert">
                            Decision recorded. Original extraction remains
                            unchanged.
                          </p>
                          {doc.status === "approved" && (
                            <button
                              className="primary"
                              disabled={busy || currentIntegrated}
                              onClick={() => setIntegrating(true)}
                            >
                              <ArrowRight size={16} />
                              {currentIntegrated
                                ? "Integrated locally"
                                : "Preview local integration"}
                            </button>
                          )}
                          <button
                            className="text-button"
                            disabled={busy}
                            onClick={() => void process()}
                          >
                            Reprocess · requires a new review
                          </button>
                        </>
                      )}
                    </div>
                  )}
                </>
              )}
            </section>
          )}
        </div>
        <footer>
          LETRANIX · Document Intelligence Platform{" "}
          <span>LOCAL WORKSPACE / NO CLOUD CONNECTION</span>
        </footer>
      </main>
      {integrating && currentReview && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="integration-title"
          >
            <h2 id="integration-title">Local integration preview</h2>
            <p>
              Creates one record in this workspace’s demonstration ledger. No
              external system is contacted.
            </p>
            <dl>
              {Object.entries(
                JSON.parse(currentReview.fields) as Record<string, string>,
              ).map(([k, v]) => (
                <React.Fragment key={k}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </React.Fragment>
              ))}
            </dl>
            <div className="decision-actions">
              <button onClick={() => setIntegrating(false)}>Cancel</button>
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await api(`/documents/${doc!.id}/integrate`, {
                      method: "POST",
                      body: JSON.stringify({
                        review_id: currentReview.id,
                        authorize: true,
                      }),
                    });
                    await select(doc!.id);
                    setNotice(
                      "Record integrated into the local demonstration ledger.",
                    );
                  })
                }
              >
                Authorize local integration
              </button>
            </div>
          </section>
        </div>
      )}
      {busy && (
        <div className="busy" role="status">
          <LoaderCircle className="spin" size={17} />
          Working locally…
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
