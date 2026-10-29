import { useEffect, useState } from "react";
import { PlugZap, RefreshCw } from "lucide-react";
import { api, formatDate, post } from "../api";
import { useShared } from "../App";
import type { OutboxEntry } from "../types";
import { Empty, PageHeader, useAction } from "../ui";

type Destination = {
  adapter: string;
  records: {
    id: string;
    review_id: string;
    document_id: string;
    fields: Record<string, string>;
    received: string;
  }[];
};

export default function Integrations() {
  const { settings, navigate } = useShared();
  const { busy, run } = useAction();
  const [outbox, setOutbox] = useState<OutboxEntry[]>([]);
  const [destination, setDestination] = useState<Destination | null>(null);
  const [destError, setDestError] = useState("");
  const [tick, setTick] = useState(0);

  useEffect(() => {
    api<OutboxEntry[]>("/integrations/outbox")
      .then(setOutbox)
      .catch(() => {});
    api<Destination>("/integrations/destination")
      .then((d) => {
        setDestination(d);
        setDestError("");
      })
      .catch((e: Error) => {
        setDestination(null);
        setDestError(e.message);
      });
  }, [tick]);
  useEffect(() => {
    if (!outbox.some((o) => o.state === "pending" || o.state === "delivering"))
      return;
    const t = setTimeout(() => setTick((n) => n + 1), 1500);
    return () => clearTimeout(t);
  }, [outbox]);

  const adapter = String(settings?.values["integration.adapter"] ?? "");
  return (
    <>
      <PageHeader
        title="Integrations"
        subtitle="Approved records reach a destination only when a reviewer authorises it. Each delivery goes through a persistent outbox with retries and idempotency keys."
        actions={
          <>
            <button onClick={() => setTick((n) => n + 1)}>
              <RefreshCw size={15} /> Refresh
            </button>
            <button onClick={() => navigate("settings")}>Configure</button>
          </>
        }
      />
      <section className="panel">
        <h2>Configured destination</h2>
        <dl className="kv">
          <dt>Adapter</dt>
          <dd>
            <code>{adapter}</code>{" "}
            {adapter === "local-ledger"
              ? "— a ledger table inside this workspace"
              : "— HTTP POST to the fictitious records API"}
          </dd>
          {adapter === "http-demo" && (
            <>
              <dt>Endpoint</dt>
              <dd>
                <code>{String(settings?.values["integration.endpoint"])}</code>
              </dd>
            </>
          )}
          <dt>Attempts before failing</dt>
          <dd>{String(settings?.values["integration.max_attempts"])}</dd>
          <dt>Contract</dt>
          <dd>
            <code>letranix.record/v1</code> — document id and hash, type, review
            (id, version, reviewer, time), approved fields, table rows and
            per-field provenance
          </dd>
        </dl>
        {adapter === "http-demo" && (
          <p className="muted small">
            Start the demo API with{" "}
            <code>python -m letranix mock-destination --port 8797</code> or run
            the service with <code>--with-destination</code>. It is a local test
            double, not a real external system.
          </p>
        )}
      </section>
      <section className="panel">
        <h2>Outbox</h2>
        {outbox.length === 0 ? (
          <Empty icon={<PlugZap size={28} />} title="Nothing sent yet">
            Open an approved document and choose “Send to destination”.
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Adapter</th>
                  <th>State</th>
                  <th className="num">Attempts</th>
                  <th>Last error</th>
                  <th>Updated</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {outbox.map((o) => (
                  <tr key={o.id}>
                    <td>
                      {o.name ? (
                        <a
                          href={"#/documents/" + o.document_id}
                          onClick={(e) => {
                            e.preventDefault();
                            navigate("documents/" + o.document_id);
                          }}
                        >
                          {o.name}
                        </a>
                      ) : (
                        <span className="muted">deleted document</span>
                      )}
                    </td>
                    <td>
                      <code>{o.adapter}</code>
                    </td>
                    <td>
                      <span className={"state " + o.state}>{o.state}</span>
                      {o.response?.duplicate === true && (
                        <small className="muted"> · duplicate suppressed</small>
                      )}
                    </td>
                    <td className="num">{o.attempts}</td>
                    <td className="issue-cell">{o.last_error || "—"}</td>
                    <td>{formatDate(o.updated, true)}</td>
                    <td>
                      {o.state === "failed" && (
                        <button
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              await post(`/integrations/outbox/${o.id}/retry`);
                              setTick((n) => n + 1);
                            }, "Delivery retried.")
                          }
                        >
                          Retry
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="panel">
        <h2>Records held by the destination</h2>
        <p className="muted small">
          Read back from the destination itself, to verify what actually
          arrived.
        </p>
        {destError ? (
          <p className="banner error">{destError}</p>
        ) : !destination?.records.length ? (
          <p className="muted">No records at the destination.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Record id</th>
                  <th>Received</th>
                  <th>Fields</th>
                </tr>
              </thead>
              <tbody>
                {destination.records.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <code>{r.id.slice(0, 12)}</code>
                    </td>
                    <td>{formatDate(r.received, true)}</td>
                    <td className="small">
                      {Object.entries(r.fields)
                        .filter(([, v]) => v)
                        .map(([k, v]) => `${k}: ${v}`)
                        .join(" · ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
