import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { CheckCircle2, Info, LoaderCircle, X, XCircle } from "lucide-react";
import type { Status } from "./types";

type Toast = { id: number; kind: "ok" | "error" | "info"; text: string };
const ToastContext = createContext<(kind: Toast["kind"], text: string) => void>(
  () => {},
);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setItems((t) => [...t.slice(-3), { id, kind, text }]);
    setTimeout(
      () => setItems((t) => t.filter((x) => x.id !== id)),
      kind === "error" ? 9000 : 4500,
    );
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map((t) => (
          <div
            key={t.id}
            className={"toast " + t.kind}
            role={t.kind === "error" ? "alert" : "status"}
          >
            {t.kind === "ok" ? (
              <CheckCircle2 size={17} />
            ) : t.kind === "error" ? (
              <XCircle size={17} />
            ) : (
              <Info size={17} />
            )}
            <span>{t.text}</span>
            <button
              className="icon ghost"
              aria-label="Dismiss notification"
              onClick={() => setItems((x) => x.filter((i) => i.id !== t.id))}
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

/** Runs an async action with busy state and error toast. */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const run = useCallback(
    async (action: () => Promise<unknown>, success?: string) => {
      setBusy(true);
      try {
        await action();
        if (success) toast("ok", success);
        return true;
      } catch (e) {
        toast("error", e instanceof Error ? e.message : "Unexpected error");
        return false;
      } finally {
        setBusy(false);
      }
    },
    [toast],
  );
  return { busy, run };
}

const STATUS_LABEL: Record<Status, string> = {
  imported: "Imported",
  queued: "Queued",
  processing: "Processing",
  "needs-review": "Needs review",
  approved: "Approved",
  rejected: "Rejected",
  error: "Error",
};

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={"badge " + status}>
      {(status === "processing" || status === "queued") && (
        <LoaderCircle size={12} className="spin" />
      )}
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function Modal({
  title,
  onClose,
  children,
  footer,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const node = ref.current;
    const focusable = () =>
      Array.from(
        node?.querySelectorAll<HTMLElement>(
          "button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),a[href]",
        ) ?? [],
      );
    focusable()[0]?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const items = focusable();
        if (!items.length) return;
        const first = items[0],
          last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          last.focus();
          e.preventDefault();
        } else if (!e.shiftKey && document.activeElement === last) {
          first.focus();
          e.preventDefault();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [onClose]);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        ref={ref}
        className={"modal" + (wide ? " wide" : "")}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header>
          <h2>{title}</h2>
          <button className="icon ghost" aria-label="Close" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </div>
    </div>
  );
}

export function Empty({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="empty">
      {icon}
      <h3>{title}</h3>
      {children && <p>{children}</p>}
    </div>
  );
}

export function Pager({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}) {
  if (total <= limit) return null;
  return (
    <div className="pager">
      <button
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - limit))}
      >
        Previous
      </button>
      <span>
        {offset + 1}–{Math.min(total, offset + limit)} of {total}
      </span>
      <button
        disabled={offset + limit >= total}
        onClick={() => onChange(offset + limit)}
      >
        Next
      </button>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}
