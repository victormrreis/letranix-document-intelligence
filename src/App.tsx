import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  Activity,
  BookOpenCheck,
  BrainCircuit,
  FileStack,
  LayoutDashboard,
  LoaderCircle,
  PlugZap,
  Settings as SettingsIcon,
  ShieldCheck,
  X,
} from "lucide-react";
import { api, post } from "./api";
import type { Job, SettingsPayload, Template } from "./types";
import { useToast } from "./ui";
import Overview from "./views/Overview";
import Library from "./views/Library";
import DocumentView from "./views/DocumentView";
import Templates from "./views/Templates";
import Learning from "./views/Learning";
import Integrations from "./views/Integrations";
import AuditView from "./views/Audit";
import Settings from "./views/Settings";

type Shared = {
  navigate: (path: string) => void;
  jobs: Job[];
  jobsTick: number;
  watchJobs: () => void;
  templates: Template[];
  reloadTemplates: () => Promise<void>;
  settings: SettingsPayload | null;
  reloadSettings: () => Promise<void>;
  setDirty: (dirty: boolean) => void;
};
const SharedContext = createContext<Shared>(null as unknown as Shared);
export const useShared = () => useContext(SharedContext);

const NAV = [
  ["overview", "Overview", LayoutDashboard],
  ["documents", "Documents", FileStack],
  ["templates", "Document types", BookOpenCheck],
  ["learning", "Learning", BrainCircuit],
  ["integrations", "Integrations", PlugZap],
  ["audit", "Audit trail", Activity],
  ["settings", "Settings", SettingsIcon],
] as const;

function currentPath() {
  return window.location.hash.replace(/^#\/?/, "") || "overview";
}

/** Query parameters carried in the hash route, e.g. #/documents?status=error. */
export function routeQuery() {
  return new URLSearchParams(currentPath().split("?")[1] ?? "");
}

export default function App() {
  const toast = useToast();
  const [path, setPath] = useState(currentPath());
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsTick, setJobsTick] = useState(0);
  const [polling, setPolling] = useState(true);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [offline, setOffline] = useState(false);
  const dirty = useRef(false);
  const lastActive = useRef<string>("");

  const navigate = useCallback((next: string) => {
    if (
      dirty.current &&
      !window.confirm(
        "You have unsaved review changes. They are kept as a draft on this device. Leave anyway?",
      )
    )
      return;
    dirty.current = false;
    window.location.hash = "/" + next;
  }, []);

  useEffect(() => {
    const onHash = () => setPath(currentPath());
    const onUnload = (e: BeforeUnloadEvent) => {
      if (dirty.current) e.preventDefault();
    };
    window.addEventListener("hashchange", onHash);
    window.addEventListener("beforeunload", onUnload);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("beforeunload", onUnload);
    };
  }, []);

  const reloadTemplates = useCallback(async () => {
    setTemplates(await api<Template[]>("/templates"));
  }, []);
  const reloadSettings = useCallback(async () => {
    setSettings(await api<SettingsPayload>("/settings"));
  }, []);

  useEffect(() => {
    Promise.all([reloadTemplates(), reloadSettings()])
      .then(() => setOffline(false))
      .catch(() => setOffline(true));
  }, [reloadTemplates, reloadSettings]);

  // Poll active jobs while any exist; announce completions.
  useEffect(() => {
    if (!polling) return;
    let stop = false;
    const tick = async () => {
      try {
        const active = await api<Job[]>("/jobs?active=true");
        if (stop) return;
        setOffline(false);
        setJobs(active);
        const signature = active.map((j) => j.id + j.progress).join();
        if (signature !== lastActive.current) {
          lastActive.current = signature;
          setJobsTick((t) => t + 1);
        }
        if (active.length === 0) setPolling(false);
      } catch {
        if (!stop) setOffline(true);
      }
    };
    void tick();
    const timer = setInterval(tick, 1200);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [polling]);

  const watchJobs = useCallback(() => setPolling(true), []);

  useEffect(() => {
    const theme = settings?.values["ui.theme"] ?? "system";
    document.documentElement.dataset.theme = String(theme);
    document.documentElement.dataset.density = String(
      settings?.values["ui.density"] ?? "comfortable",
    );
  }, [settings]);

  const [section, id] = path.split("?")[0].split("/");
  const shared: Shared = {
    navigate,
    jobs,
    jobsTick,
    watchJobs,
    templates,
    reloadTemplates,
    settings,
    reloadSettings,
    setDirty: (d) => (dirty.current = d),
  };

  let view: React.ReactNode;
  if (section === "documents" && id) view = <DocumentView id={id} key={id} />;
  else if (section === "documents") view = <Library />;
  else if (section === "templates") view = <Templates />;
  else if (section === "learning") view = <Learning />;
  else if (section === "integrations") view = <Integrations />;
  else if (section === "audit") view = <AuditView />;
  else if (section === "settings") view = <Settings />;
  else view = <Overview />;

  return (
    <SharedContext.Provider value={shared}>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <div className="app">
        <nav className="sidebar" aria-label="Main">
          <a
            className="brand"
            href="#/overview"
            onClick={(e) => {
              e.preventDefault();
              navigate("overview");
            }}
          >
            <img src="/mark.svg" alt="" />
            <span>
              LETRANIX<small>Document intelligence</small>
            </span>
          </a>
          <ul>
            {NAV.map(([key, label, Icon]) => (
              <li key={key}>
                <a
                  href={"#/" + key}
                  aria-current={section === key ? "page" : undefined}
                  className={section === key ? "active" : ""}
                  onClick={(e) => {
                    e.preventDefault();
                    navigate(key);
                  }}
                >
                  <Icon size={18} />
                  {label}
                </a>
              </li>
            ))}
          </ul>
          {jobs.length > 0 && (
            <div className="jobs-tray" aria-live="polite">
              <strong>
                <LoaderCircle size={14} className="spin" /> Processing{" "}
                {jobs.length}
              </strong>
              {jobs.slice(0, 4).map((j) => (
                <div key={j.id} className="job-line">
                  <span title={j.name}>{j.name}</span>
                  <small>
                    {j.state === "queued"
                      ? "queued"
                      : `page ${j.progress}/${j.total || "?"}`}
                  </small>
                  <button
                    className="icon ghost"
                    aria-label={`Cancel processing of ${j.name}`}
                    onClick={() =>
                      post(`/jobs/${j.id}/cancel`)
                        .then(() => toast("info", "Cancellation requested"))
                        .catch((e: Error) => toast("error", e.message))
                    }
                  >
                    <X size={13} />
                  </button>
                </div>
              ))}
            </div>
          )}
          <div className="sidebar-foot">
            <ShieldCheck size={18} />
            <p>
              Local processing on this device. External destinations only on
              explicit request.
            </p>
            <small>
              v{settings?.version ?? "…"} · schema {settings?.schema_version}
            </small>
          </div>
        </nav>
        <main id="main" tabIndex={-1}>
          {offline && (
            <div className="banner error" role="alert">
              The LETRANIX service is not responding. Start it with{" "}
              <code>python -m letranix serve</code> — retrying automatically.
            </div>
          )}
          {view}
        </main>
      </div>
    </SharedContext.Provider>
  );
}
