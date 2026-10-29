export type Status =
  | "imported"
  | "queued"
  | "processing"
  | "needs-review"
  | "approved"
  | "rejected"
  | "error";

export type FieldDef = {
  key: string;
  label: string;
  type: "text" | "identifier" | "date" | "number" | "money" | "enum";
  labels: string[];
  required: boolean;
  pattern?: string;
  options?: string[];
};

export type Template = {
  id: string;
  name: string;
  description: string;
  keywords: string[];
  fields: FieldDef[];
  table?: { key: string; label: string; columns: FieldDef[] };
  builtin?: boolean;
};

export type Extracted = {
  value: string;
  raw: string;
  source: "recognized" | "inferred" | "missing";
  rule: string;
  page: number | null;
  row: number | null;
  evidence: string;
  bbox: number[] | null;
  ocr_score: number | null;
  ambiguous: boolean;
  candidates: string[];
  issues: string[];
  learned: string[];
};

export type Segment = { text: string; bbox: number[]; score: number };
export type Row = {
  text: string;
  segments: Segment[];
  bbox: number[] | null;
  score: number | null;
};

export type PageDetail = {
  page: number;
  method: string;
  width: number;
  height: number;
  rows: Row[];
  mean_score: number | null;
  steps: string[];
  has_image: boolean;
  ms: number;
};

export type Summary = {
  id: string;
  name: string;
  mime: string;
  created: string;
  updated: string;
  status: Status;
  version: number;
  method: string;
  template_id: string;
  template_source: string;
  pages: number;
  size: number;
  archived: number;
  issue_count: number;
};

export type Job = {
  id: string;
  document_id: string;
  name?: string;
  state: string;
  created: string;
  started: string;
  finished: string;
  error: string;
  progress: number;
  total: number;
  timings: Record<string, number>;
};

export type ReviewRecord = {
  id: string;
  version: number;
  decision: "approved" | "rejected";
  actor: string;
  reason: string;
  created: string;
  template_id: string;
  fields: Record<string, string>;
  provenance: Record<string, string>;
  issues: Record<string, string>;
  tables: { rows?: Record<string, string>[] };
};

export type AuditEntry = {
  id: number;
  document_id: string | null;
  name?: string | null;
  event: string;
  actor: string;
  detail: Record<string, unknown>;
  created: string;
};

export type OutboxEntry = {
  id: string;
  review_id: string;
  document_id: string;
  adapter: string;
  state: string;
  attempts: number;
  last_error: string;
  response: Record<string, unknown>;
  created: string;
  updated: string;
  next_attempt?: string;
  name?: string;
};

export type TableResult = {
  key: string;
  columns: string[];
  rows: { cells: Record<string, string>; page: number; row: number }[];
  header: { page: number; row: number } | null;
};

export type Detail = Summary & {
  digest: string;
  text: string;
  fields: Record<string, Extracted>;
  classification: { template: string; probability: number }[];
  tables: {
    table?: TableResult | null;
    pairs?: { label: string; value: string; page: number; row: number }[];
  };
  jobs: Job[];
  reviews: ReviewRecord[];
  audit: AuditEntry[];
  outbox: OutboxEntry[];
  pages_detail: PageDetail[];
  template: Template | null;
};

export type SettingSpec = {
  key: string;
  default: unknown;
  kind: string;
  label: string;
  group: string;
  minimum: number | null;
  maximum: number | null;
  choices: string[];
  help: string;
};

export type SettingsPayload = {
  values: Record<string, string | number | boolean>;
  schema: SettingSpec[];
  engines: Record<string, boolean>;
  workspace: string;
  schema_version: number;
  version: string;
};

export type Rule = {
  id: string;
  template_id: string;
  field: string;
  kind: string;
  pattern: string;
  replacement: string;
  support: number;
  applied: number;
  rejected: number;
  enabled: number;
  active: boolean;
  updated: string;
};

export type EvalSplit = {
  documents: number;
  template_accuracy: number;
  field_accuracy: number;
  fields_evaluated: number;
  invented_values: number;
  per_field: Record<string, number>;
};

export type Evaluation = {
  generated: string;
  method: string;
  splits: Record<string, number>;
  min_support_selection: Record<string, number>;
  min_support_chosen: number;
  rules_active: Record<string, number>;
  test_before_learning: EvalSplit;
  test_after_learning: EvalSplit;
  seconds: number;
};

export type Overview = {
  by_status: Record<string, number>;
  by_template: Record<string, number>;
  archived: number;
  processing: { jobs: number; avg_ms: number; max_ms: number };
  review: { approved_fields: number; corrections: number };
  learning: { rules: number; active: number; applied: number };
  outbox: Record<string, number>;
  recent: {
    event: string;
    created: string;
    document_id: string | null;
    name: string | null;
  }[];
};
