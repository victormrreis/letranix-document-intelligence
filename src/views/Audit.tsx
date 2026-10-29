import { useEffect, useState } from "react";
import { api, formatDate } from "../api";
import { useShared } from "../App";
import type { AuditEntry } from "../types";
import { PageHeader, Pager } from "../ui";

const LIMIT = 50;

export default function AuditView() {
  const { navigate } = useShared();
  const [event, setEvent] = useState("");
  const [actor, setActor] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{
    items: AuditEntry[];
    total: number;
    events: string[];
  }>({
    items: [],
    total: 0,
    events: [],
  });
  useEffect(() => {
    const params = new URLSearchParams({
      event,
      actor,
      limit: String(LIMIT),
      offset: String(offset),
    });
    api<typeof data>(`/audit?${params}`)
      .then(setData)
      .catch(() => {});
  }, [event, actor, offset]);
  const prefixes = [...new Set(data.events.map((e) => e.split(".")[0]))];
  return (
    <>
      <PageHeader
        title="Audit trail"
        subtitle="Every import, processing run, extraction, review decision, export, delivery, setting change and backup. Entries hold identifiers and codes, never document text."
      />
      <div className="filters">
        <select
          aria-label="Event type"
          value={event}
          onChange={(e) => {
            setOffset(0);
            setEvent(e.target.value);
          }}
        >
          <option value="">All events</option>
          {prefixes.map((p) => (
            <optgroup key={p} label={p}>
              <option value={p + "."}>{p}.*</option>
              {data.events
                .filter((e) => e.startsWith(p + "."))
                .map((e) => (
                  <option key={e} value={e}>
                    {e}
                  </option>
                ))}
            </optgroup>
          ))}
        </select>
        <input
          aria-label="Actor"
          placeholder="Actor (exact)"
          value={actor}
          onChange={(e) => {
            setOffset(0);
            setActor(e.target.value);
          }}
        />
        <span className="muted">{data.total} events</span>
      </div>
      <div className="table-wrap">
        <table className="audit">
          <thead>
            <tr>
              <th>When</th>
              <th>Event</th>
              <th>Actor</th>
              <th>Document</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((a) => (
              <tr key={a.id}>
                <td>{formatDate(a.created, true)}</td>
                <td>
                  <code>{a.event}</code>
                </td>
                <td>{a.actor}</td>
                <td>
                  {a.document_id ? (
                    a.name ? (
                      <a
                        href={"#/documents/" + a.document_id}
                        onClick={(e) => {
                          e.preventDefault();
                          navigate("documents/" + a.document_id);
                        }}
                      >
                        {a.name}
                      </a>
                    ) : (
                      <span className="muted">
                        {a.document_id.slice(0, 8)} (deleted)
                      </span>
                    )
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="detail-cell">
                  {Object.entries(a.detail)
                    .filter(
                      ([, v]) =>
                        v !== "" &&
                        v !== null &&
                        !(Array.isArray(v) && !v.length),
                    )
                    .map(
                      ([k, v]) =>
                        `${k}=${Array.isArray(v) ? v.join(",") : String(v)}`,
                    )
                    .join("  ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pager
        total={data.total}
        limit={LIMIT}
        offset={offset}
        onChange={setOffset}
      />
    </>
  );
}
