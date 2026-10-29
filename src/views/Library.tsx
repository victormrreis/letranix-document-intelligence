import { useEffect, useRef, useState } from "react";
import {
  Archive,
  Download,
  FileImage,
  FileText,
  FolderInput,
  Play,
  Search,
  Upload,
} from "lucide-react";
import { api, download, formatBytes, formatDate, post } from "../api";
import { routeQuery, useShared } from "../App";
import type { Summary } from "../types";
import {
  Empty,
  PageHeader,
  Pager,
  StatusBadge,
  useAction,
  useToast,
} from "../ui";

const STATUSES = [
  "imported",
  "queued",
  "processing",
  "needs-review",
  "approved",
  "rejected",
  "error",
];
const LIMIT = 25;

export default function Library() {
  const { navigate, templates, jobsTick, watchJobs } = useShared();
  const toast = useToast();
  const { busy, run } = useAction();
  const initial = routeQuery();
  const [filters, setFilters] = useState({
    q: "",
    status: initial.get("status") ?? "",
    template: "",
    date_from: "",
    date_to: "",
    archived: initial.get("archived") === "1",
    issues: false,
    sort: "created",
  });
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ items: Summary[]; total: number }>({
    items: [],
    total: 0,
  });
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [dragging, setDragging] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    const params = new URLSearchParams({
      ...Object.fromEntries(
        Object.entries(filters).map(([k, v]) => [k, String(v)]),
      ),
      limit: String(LIMIT),
      offset: String(offset),
    });
    const timer = setTimeout(
      () =>
        api<{ items: Summary[]; total: number }>(`/documents?${params}`)
          .then((d) => active && setData(d))
          .catch((e: Error) => active && toast("error", e.message))
          .finally(() => active && setLoading(false)),
      filters.q ? 200 : 0,
    );
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [filters, offset, jobsTick, refresh, toast]);

  const set = (patch: Partial<typeof filters>) => {
    setOffset(0);
    setSelected(new Set());
    setFilters((f) => ({ ...f, ...patch }));
  };

  async function upload(files: FileList | File[] | null) {
    if (!files || !files.length) return;
    let imported = 0,
      duplicates = 0;
    const failures: string[] = [];
    await run(async () => {
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        try {
          const r = await api<{ duplicate: boolean }>("/documents", {
            method: "POST",
            body: form,
          });
          if (r.duplicate) duplicates++;
          else imported++;
        } catch (e) {
          failures.push(`${file.name}: ${(e as Error).message}`);
        }
      }
    });
    if (imported)
      toast(
        "ok",
        `${imported} document(s) imported${duplicates ? `, ${duplicates} already in the library` : ""}.`,
      );
    else if (duplicates)
      toast("info", `${duplicates} document(s) already in the library.`);
    failures.forEach((f) => toast("error", f));
    if (input.current) input.current.value = "";
    watchJobs();
    setRefresh((r) => r + 1);
  }

  const name = (id: string) =>
    templates.find((t) => t.id === id)?.name ?? (id || "—");
  const ids = [...selected];
  const allSelected =
    data.items.length > 0 && data.items.every((i) => selected.has(i.id));

  return (
    <div
      className={"library" + (dragging ? " dragging" : "")}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        void upload(e.dataTransfer.files);
      }}
    >
      <PageHeader
        title="Documents"
        subtitle="Import, search and track every document in this workspace. Drop files anywhere on this page."
        actions={
          <>
            <button
              disabled={busy}
              onClick={() =>
                run(async () => {
                  const r = await post<{
                    imported: number;
                    duplicates: number;
                    rejected: { name: string; reason: string }[];
                  }>("/documents/inbox");
                  toast(
                    "ok",
                    `Inbox: ${r.imported} imported, ${r.duplicates} duplicates, ${r.rejected.length} rejected.`,
                  );
                  r.rejected.forEach((x) =>
                    toast("error", `${x.name}: ${x.reason}`),
                  );
                  watchJobs();
                  setRefresh((n) => n + 1);
                })
              }
            >
              <FolderInput size={16} /> Import from inbox
            </button>
            <button
              className="primary"
              disabled={busy}
              onClick={() => input.current?.click()}
            >
              <Upload size={16} /> Import files
            </button>
            <input
              ref={input}
              type="file"
              hidden
              multiple
              accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.webp,.txt"
              onChange={(e) => void upload(e.target.files)}
              aria-label="Choose documents to import"
            />
          </>
        }
      />
      <div className="filters" role="search">
        <label className="search">
          <Search size={16} />
          <input
            aria-label="Search documents"
            placeholder="Search names, extracted text and field values"
            value={filters.q}
            maxLength={200}
            onChange={(e) => set({ q: e.target.value })}
          />
        </label>
        <select
          aria-label="Filter by status"
          value={filters.status}
          onChange={(e) => set({ status: e.target.value })}
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace("-", " ")}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter by document type"
          value={filters.template}
          onChange={(e) => set({ template: e.target.value })}
        >
          <option value="">All types</option>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
        <label className="inline">
          From
          <input
            type="date"
            aria-label="Imported from"
            value={filters.date_from}
            onChange={(e) => set({ date_from: e.target.value })}
          />
        </label>
        <label className="inline">
          To
          <input
            type="date"
            aria-label="Imported until"
            value={filters.date_to}
            onChange={(e) => set({ date_to: e.target.value })}
          />
        </label>
        <select
          aria-label="Sort"
          value={filters.sort}
          onChange={(e) => set({ sort: e.target.value })}
        >
          <option value="created">Newest first</option>
          <option value="updated">Recently changed</option>
          <option value="name">Name</option>
          <option value="status">Status</option>
        </select>
        <label className="check">
          <input
            type="checkbox"
            checked={filters.issues}
            onChange={(e) => set({ issues: e.target.checked })}
          />
          With issues
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={filters.archived}
            onChange={(e) => set({ archived: e.target.checked })}
          />
          Archived
        </label>
      </div>
      <div className="toolbar">
        <span className="muted">
          {data.total} document{data.total === 1 ? "" : "s"}
          {ids.length > 0 && ` · ${ids.length} selected`}
        </span>
        <div className="actions">
          <button
            disabled={!ids.length || busy}
            onClick={() =>
              run(async () => {
                await post("/documents/process", { ids });
                setSelected(new Set());
                watchJobs();
              }, `${ids.length} document(s) queued for processing.`)
            }
          >
            <Play size={15} /> Process selected
          </button>
          <button
            disabled={!ids.length || busy}
            onClick={() =>
              run(
                async () => {
                  for (const id of ids)
                    await post(`/documents/${id}/archive`, {
                      archived: !filters.archived,
                    });
                  setSelected(new Set());
                  setRefresh((n) => n + 1);
                },
                filters.archived ? "Restored from archive." : "Archived.",
              )
            }
          >
            <Archive size={15} /> {filters.archived ? "Unarchive" : "Archive"}
          </button>
          <button
            onClick={() =>
              run(() =>
                download(
                  `/export?format=csv&template=${filters.template}`,
                  "letranix-approved.csv",
                ),
              )
            }
          >
            <Download size={15} /> Approved CSV
          </button>
          <button
            onClick={() =>
              run(() =>
                download(
                  `/export?format=json&template=${filters.template}`,
                  "letranix-approved.json",
                ),
              )
            }
          >
            <Download size={15} /> JSON
          </button>
        </div>
      </div>
      {loading ? (
        <div className="loading">Loading documents…</div>
      ) : data.items.length === 0 ? (
        <Empty icon={<FileText size={30} />} title="No documents in this view">
          Import PDF, PNG, JPEG, TIFF, WebP or UTF-8 text — or change the
          filters. Generate synthetic examples with{" "}
          <code>python -m letranix demo</code>.
        </Empty>
      ) : (
        <div className="table-wrap">
          <table className="documents">
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    aria-label="Select all in view"
                    checked={allSelected}
                    onChange={(e) =>
                      setSelected(
                        e.target.checked
                          ? new Set(data.items.map((i) => i.id))
                          : new Set(),
                      )
                    }
                  />
                </th>
                <th>Document</th>
                <th>Type</th>
                <th>Status</th>
                <th className="num">Pages</th>
                <th className="num">Issues</th>
                <th>Imported</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((d) => (
                <tr key={d.id} className={selected.has(d.id) ? "picked" : ""}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Select ${d.name}`}
                      checked={selected.has(d.id)}
                      onChange={(e) => {
                        const next = new Set(selected);
                        if (e.target.checked) next.add(d.id);
                        else next.delete(d.id);
                        setSelected(next);
                      }}
                    />
                  </td>
                  <td>
                    <a
                      className="doc-link"
                      href={"#/documents/" + d.id}
                      onClick={(e) => {
                        e.preventDefault();
                        navigate("documents/" + d.id);
                      }}
                    >
                      {d.mime.startsWith("image/") ? (
                        <FileImage size={17} />
                      ) : (
                        <FileText size={17} />
                      )}
                      <span>
                        {d.name}
                        <small>
                          {d.mime.split("/")[1].toUpperCase()} ·{" "}
                          {formatBytes(d.size)} · v{d.version}
                        </small>
                      </span>
                    </a>
                  </td>
                  <td>{name(d.template_id)}</td>
                  <td>
                    <StatusBadge status={d.status} />
                  </td>
                  <td className="num">{d.pages || "—"}</td>
                  <td className="num">
                    {d.issue_count ? (
                      <span className="warn-count">{d.issue_count}</span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{formatDate(d.created)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager
        total={data.total}
        limit={LIMIT}
        offset={offset}
        onChange={setOffset}
      />
      {dragging && (
        <div className="drop-hint">
          <Upload size={28} /> Drop to import
        </div>
      )}
    </div>
  );
}
