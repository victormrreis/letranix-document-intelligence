import React, { useEffect, useState } from "react";
import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  FileStack,
  PlugZap,
} from "lucide-react";
import { api, formatDate, ms } from "../api";
import { useShared } from "../App";
import type { Overview as OverviewData } from "../types";
import { PageHeader } from "../ui";

export default function Overview() {
  const { navigate, jobsTick, templates } = useShared();
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<OverviewData>("/overview")
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, [jobsTick]);
  if (error) return <div className="banner error">{error}</div>;
  if (!data) return <div className="loading">Loading workspace…</div>;
  const total = Object.values(data.by_status).reduce((a, b) => a + b, 0);
  const s = (k: string) => data.by_status[k] ?? 0;
  const name = (id: string) => templates.find((t) => t.id === id)?.name ?? id;
  const cards = [
    {
      icon: FileStack,
      label: "Active documents",
      value: total,
      hint: `${data.archived} archived`,
      go: "documents",
    },
    {
      icon: Clock3,
      label: "Awaiting review",
      value: s("needs-review"),
      hint: `${s("queued") + s("processing")} in the processing queue`,
      go: "documents?status=needs-review",
    },
    {
      icon: CheckCircle2,
      label: "Approved",
      value: s("approved"),
      hint: `${s("rejected")} rejected`,
      go: "documents?status=approved",
    },
    {
      icon: AlertTriangle,
      label: "Processing errors",
      value: s("error"),
      hint: "Open to see the cause and retry",
      go: "documents?status=error",
    },
  ];
  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="Live figures from this workspace's database. Nothing on this page is sample data."
        actions={
          <button className="primary" onClick={() => navigate("documents")}>
            Open documents
          </button>
        }
      />
      <div className="stat-grid">
        {cards.map(({ icon: Icon, label, value, hint, go }) => (
          <button key={label} className="stat" onClick={() => navigate(go)}>
            <Icon size={20} />
            <span className="stat-label">{label}</span>
            <strong>{value}</strong>
            <small>{hint}</small>
          </button>
        ))}
      </div>
      <div className="grid-2">
        <section className="panel">
          <h2>Processing</h2>
          <dl className="kv">
            <dt>Completed jobs</dt>
            <dd>{data.processing.jobs}</dd>
            <dt>Mean time per document</dt>
            <dd>{ms(data.processing.avg_ms)}</dd>
            <dt>Slowest document</dt>
            <dd>{ms(data.processing.max_ms)}</dd>
          </dl>
          <h3>By document type</h3>
          {Object.keys(data.by_template).length === 0 ? (
            <p className="muted">No processed documents yet.</p>
          ) : (
            <ul className="bars">
              {Object.entries(data.by_template).map(([id, n]) => (
                <li key={id}>
                  <span>{name(id)}</span>
                  <i style={{ width: `${(n / Math.max(1, total)) * 100}%` }} />
                  <b>{n}</b>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="panel">
          <h2>
            <BrainCircuit size={18} /> Learning from review
          </h2>
          <dl className="kv">
            <dt>Approved field values</dt>
            <dd>{data.review.approved_fields}</dd>
            <dt>Human corrections recorded</dt>
            <dd>{data.review.corrections}</dd>
            <dt>Learned rules (active / total)</dt>
            <dd>
              {data.learning.active} / {data.learning.rules}
            </dd>
            <dt>Times rules were applied</dt>
            <dd>{data.learning.applied}</dd>
          </dl>
          <h2>
            <PlugZap size={18} /> Integration deliveries
          </h2>
          <dl className="kv">
            {["pending", "delivering", "delivered", "failed"].map((k) => (
              <React.Fragment key={k}>
                <dt>{k}</dt>
                <dd>{data.outbox[k] ?? 0}</dd>
              </React.Fragment>
            ))}
          </dl>
        </section>
      </div>
      <section className="panel">
        <div className="panel-head">
          <h2>Recent activity</h2>
          <button className="ghost" onClick={() => navigate("audit")}>
            Full audit trail
          </button>
        </div>
        <ul className="activity">
          {data.recent.map((r, i) => (
            <li key={i}>
              <code>{r.event}</code>
              {r.document_id && r.name ? (
                <a
                  href={"#/documents/" + r.document_id}
                  onClick={(e) => {
                    e.preventDefault();
                    navigate("documents/" + r.document_id);
                  }}
                >
                  {r.name}
                </a>
              ) : (
                <span className="muted">workspace</span>
              )}
              <time>{formatDate(r.created, true)}</time>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
