import { useEffect, useState } from "react";

let token = "";
let pending: Promise<string> | null = null;

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public fields: Record<string, string[]> = {},
  ) {
    super(message);
  }
}

async function session(): Promise<string> {
  if (token) return token;
  // Concurrent first requests share one session handshake.
  pending ??= fetch("/api/session", {
    headers: { "X-Letranix-Client": "browser" },
  })
    .then(async (r) => {
      if (!r.ok) throw new ApiError("Cannot start a local session", r.status);
      token = (await r.json()).token;
      return token;
    })
    .finally(() => (pending = null));
  return pending;
}

async function request(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${await session()}`);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  let r: Response;
  try {
    r = await fetch("/api" + path, { ...init, headers });
  } catch {
    throw new ApiError(
      "The local LETRANIX service is not reachable. Is it running?",
      0,
    );
  }
  if (r.status === 401) token = ""; // Service restarted: next call renews the session.
  if (!r.ok) {
    let detail: unknown = null;
    let fields: Record<string, string[]> = {};
    try {
      const body = await r.json();
      detail = body.detail;
      fields = body.fields ?? {};
    } catch {
      /* non-JSON error body */
    }
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? "Some values are invalid: " +
            detail
              .map((d: { loc?: string[] }) => d.loc?.slice(-1)[0])
              .join(", ")
          : `Request failed (${r.status})`;
    throw new ApiError(message, r.status, fields);
  }
  return r;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await request(path, init)).json();
}

export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export async function blob(path: string): Promise<Blob> {
  return (await request(path)).blob();
}

/** Download an authenticated resource through a temporary object URL. */
export async function download(path: string, filename: string) {
  const url = URL.createObjectURL(await blob(path));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Object URL for an authenticated image; revoked when the path changes or on unmount. */
export function useBlobUrl(path: string | null) {
  const [url, setUrl] = useState<string>("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let created = "";
    setUrl("");
    setError("");
    if (path)
      blob(path)
        .then((b) => {
          created = URL.createObjectURL(b);
          if (active) setUrl(created);
        })
        .catch((e: Error) => active && setError(e.message));
    return () => {
      active = false;
      if (created) URL.revokeObjectURL(created);
    };
  }, [path]);
  return { url, error };
}

export function formatBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDate(iso: string, withTime = false) {
  if (!iso) return "—";
  const d = new Date(iso);
  return withTime ? d.toLocaleString() : d.toLocaleDateString();
}

export function ms(value: number | undefined) {
  if (value === undefined || value === null) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${value} ms`;
}
