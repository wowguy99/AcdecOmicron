export interface TagInfo {
  name: string;
  definition: string;
  builtin: number;
}

export interface SubsectionTagCount {
  name: string;
  definition: string;
  builtin: number;
  count: number;
}

export interface SubsectionInfo {
  node_id: number;
  title: string;
  section_type: string;
  subheader_kind: string;
  first_sentence: string;
  last_sentence: string;
  pdf_start_page: number | null;
  pdf_end_page: number | null;
  printed_start_page: number | null;
  printed_end_page: number | null;
  body_char_count: number;
  caption_char_count: number;
  cards_total: number;
  tag_counts: SubsectionTagCount[];
}

export interface TreeNode {
  id: number;
  title: string;
  tier: "section" | "subheader";
  section_type: string;
  excluded: boolean;
  deterministic: boolean;
  validated: boolean;
  cards_a: number;
  cards_b: number;
  chunks_pending?: number;
  chunks_done?: number;
  chunks_failed?: number;
  children: TreeNode[];
}

export interface JobInfo {
  status: string;
  message: string;
  total: number;
  completed: number;
}

export interface ChunkError {
  id: number;
  idx: number;
  track: string;
  error: string;
  attempts: number;
  node_title: string;
  section_title: string | null;
  tier: string;
}

export interface ValidationFlag {
  code: string;
  severity: "error" | "warn" | "info";
  message: string;
}

export interface ValidationItem {
  card_id: number;
  front: string;
  back: string;
  tag: string;
  track: string;
  source: string;
  flags: ValidationFlag[];
  source_snippet: string;
  grounding_ratio: number | null;
  ai_verdict: "ok" | "error" | null;
  ai_message: string;
  needs_attention: boolean;
}

export interface ValidationReport {
  node_id: number;
  title: string;
  track: "A" | "master";
  items: ValidationItem[];
  issue_count: number;
  reviewed_count: number;
  total_count: number;
  auto_passed_count: number;
  flagged_count: number;
  ai_calls: number;
  warning: string | null;
}

export interface Tree {
  subject: {
    id: number;
    name: string;
    status: string;
    page_count: number;
    is_iad?: boolean;
    cards_a: number;
    cards_b: number;
    all_validated: boolean;
  };
  tags: TagInfo[];
  job: JobInfo | null;
  chunk_errors: ChunkError[];
  sections: TreeNode[];
}

export interface SubjectSummary {
  id: number;
  name: string;
  filename: string;
  page_count: number;
  status: string;
  created_at: string;
  is_iad?: boolean;
}

export interface Card {
  id: number;
  front: string;
  back: string;
  tag: string;
  track: string;
  source: string;
}

export interface ProviderConfig {
  provider: string;
  model: string;
  api_key: boolean | string;
  base_url: string | null;
  rpm: number;
  rpd: number;
  temperature: number;
  text_export_format: "csv" | "google_sheet";
  google_client_id: string;
  google_connected: boolean;
}

export interface SheetExportResult {
  url: string;
  format: "google_sheet";
}

export type LicenseStatusCode =
  | "valid"
  | "expired"
  | "wrong_machine"
  | "bad_signature"
  | "malformed"
  | "missing";

export interface LicenseStatus {
  machine_id: string;
  status: LicenseStatusCode;
  expires_at: number | null;
  expires_iso: string | null;
  has_key: boolean;
}
