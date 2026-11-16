import { ApiError, getApiBaseUrl } from '../api/client';

function root() {
  return getApiBaseUrl().replace(/\/$/, '').replace(/\/api\/v1$/, '');
}

async function patientsFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${root()}/api/patients${path.startsWith('/') ? path : `/${path}`}`;
  const headers = new Headers(options.headers || {});
  const isForm = typeof FormData !== 'undefined' && options.body instanceof FormData;
  if (options.body && !isForm && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  let response: Response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch {
    throw new ApiError(0, null, 'Unable to reach the patient analytics API. Check that the backend is running.');
  }
  if (!response.ok) {
    let body = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    throw new ApiError(response.status, body, `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export type Brand = { brand: string; description: string };
export type Overview = {
  rows_processed: number;
  files?: number;
  patients: number;
  mapped_automatically_pct: number;
  needs_review: number;
  as_of_label: string | null;
  brands: Brand[];
  small_cell_min: number;
};
export type LayerCard = {
  layer: string;
  title: string;
  description: string;
  example: string;
  count: number;
  pct: number;
};
export type Mapping = { records: number; layers: LayerCard[]; quality_line: string | null };
export type SourceCard = {
  source: string;
  label: string;
  description: string;
  rows: number;
  vendor_patients: number;
  mapped_pct: number;
  files: { id: number; name: string; kind: string; period: string | null; rows: number; rows_held_back: number; loaded_at?: string | null }[];
};
export type RunRow = {
  id: number;
  input: string;
  rows: number;
  new_patients: number;
  added_to_existing: number;
  review_count: number;
  status: string;
  duration?: number | null;
  started_at: string;
  finished_at: string | null;
  steps?: { title: string; detail: string; status: string; at?: string }[];
  result?: { updated_patient_ids?: string[]; patients?: number; reviews?: number };
};
export type PatientRow = {
  daiichi_patient_id: string;
  age_band: string;
  sex: string;
  payer_type: string;
  brand: string;
  description: string;
  status: string;
  next_dose_label: string | null;
  overdue: boolean;
  stop_date_label: string | null;
  prescriber: string;
  doctor_id: string | null;
  pharmacy: string | null;
  previous_pharmacy?: string | null;
  switched: boolean;
  sources: string[];
  pending: boolean;
};
export type PatientList = {
  items: PatientRow[];
  total: number;
  counts: Record<string, number>;
  mapped_automatically_pct: number;
  as_of_label: string | null;
};
export type SummaryText = { paragraphs: string[]; template: boolean; model: string };
export type PatientDetail = {
  daiichi_patient_id: string;
  status: string;
  brand: string;
  description: string;
  age_band: string;
  sex: string;
  payer_type: string;
  prescriber: string;
  doctor_id: string | null;
  sources: string[];
  record_count?: number;
  pending_reviews: { review_id: number; ref: string }[];
  as_of_label: string | null;
  kpis: {
    next_dose_label: string | null;
    overdue: boolean;
    stop_date_label: string | null;
    stop_reason: string | null;
    current_quantity: number | null;
    unit: string | null;
    dose_count: number;
    first_dose_label: string | null;
    pharmacy: string | null;
    previous_pharmacy: string | null;
    switch_date_label: string | null;
  };
  summary: SummaryText;
};
export type TimelineEvent = {
  date: string;
  date_label: string;
  source: string;
  source_label?: string;
  kind: string;
  title: string;
  detail: string | null;
  quantity: number | null;
  pharmacy: string | null;
  flags: Record<string, unknown>;
  ref: string | null;
};
export type RecordLink = {
  ref: string;
  source: string;
  source_label: string;
  vendor_patient_id: string;
  layer: string;
  reason: string | null;
  score: number | null;
  score_items: { label: string; points: number }[];
  first_date: string | null;
};
export type ReviewItem = {
  id: number;
  ref: string;
  source: string;
  source_label: string;
  vendor_patient_id: string;
  best_score: number | null;
  candidates?: number;
};
export type EvidenceCell = { symbol: string; tone: string; text: string };
export type ReviewDetail = {
  id: number;
  status: string;
  record: {
    ref: string;
    source?: string;
    source_label: string;
    vendor_patient_id: string;
    birth_year: number;
    sex: string;
    zip3: string;
    prescriber: string;
    doctor_id: string | null;
    brand: string;
    payer_type: string;
    first_date_label: string | null;
    hub_case_ids?: string[];
    copay_card_ids?: string[];
    row_count?: number;
  };
  candidates: {
    daiichi_patient_id: string;
    score: number;
    probability: number;
    suggested: boolean;
    items: { label: string; points: number }[];
    profile: {
      sources: string[];
      record_count: number;
      prescriber: string;
      brand: string;
      birth_year?: number | null;
      sex?: string | null;
      zip3?: string | null;
    } | null;
    evidence: { field: string; record: string | number | null; candidate: EvidenceCell }[];
  }[];
  reasoning: {
    recommendation?: string;
    why_not_auto?: string;
    agrees?: string[];
    differs?: string[];
    why_not_others?: string;
    what_happens_next?: string;
    template?: boolean;
  };
};

export const fetchOverview = (signal?: AbortSignal) => patientsFetch<Overview>('/overview', { signal });
export const fetchMapping = (signal?: AbortSignal) => patientsFetch<Mapping>('/mapping', { signal });
export const fetchMappingLayer = (layer: string, signal?: AbortSignal) =>
  patientsFetch<{ records: { ref: string; source_label: string; reason: string | null; daiichi_patient_id: string | null }[] }>(
    `/mapping/${layer}`,
    { signal },
  );
export const fetchSources = (signal?: AbortSignal) => patientsFetch<{ sources: SourceCard[] }>('/sources', { signal });
export const fetchFile = (id: number, signal?: AbortSignal) =>
  patientsFetch<{
    name: string;
    source?: string;
    kind?: string;
    period?: string | null;
    row_count?: number;
    vendor_patients?: number;
    rows_held_back?: number;
    columns: string[];
    rows: { values: Record<string, string>; held_back?: boolean; reason?: string | null }[];
  }>(`/files/${id}`, { signal });
export const fetchRuns = (signal?: AbortSignal) => patientsFetch<{ runs: RunRow[] }>('/runs', { signal });
export const fetchRun = (id: number, signal?: AbortSignal) => patientsFetch<RunRow>(`/runs/${id}`, { signal });
export const reprocess = () => patientsFetch<{ run_id: number }>('/reprocess', { method: 'POST' });
export const uploadPreview = (source: string, file: File) => {
  const body = new FormData();
  body.set('source', source);
  body.set('file', file);
  return patientsFetch<{
    upload_id: string;
    filename?: string;
    rejected: boolean;
    reject_reason: string;
    identifier_ok: boolean;
    identifier_message: string;
    rows: number;
    rows_held_back: number;
    mapping: { field: string; label: string; column: string | null; state: string; required?: boolean }[];
    preview_rows: Record<string, string>[];
  }>('/upload', { method: 'POST', body });
};
export const processUpload = (id: string) => patientsFetch<{ run_id: number }>(`/upload/${id}/process`, { method: 'POST' });
export const fetchPatients = (query: string, signal?: AbortSignal) => patientsFetch<PatientList>(`?${query}`, { signal });
export const fetchPatient = (id: string, signal?: AbortSignal) => patientsFetch<PatientDetail>(`/${id}`, { signal });
export const fetchTimeline = (id: string, signal?: AbortSignal) =>
  patientsFetch<{ events: TimelineEvent[] }>(`/${id}/timeline`, { signal });
export const fetchDoses = (id: string, signal?: AbortSignal) =>
  patientsFetch<{ doses: TimelineEvent[]; next_dose_label: string | null; unit: string | null }>(`/${id}/doses`, { signal });
export const fetchRecords = (id: string, signal?: AbortSignal) =>
  patientsFetch<{
    records: RecordLink[];
    lineage: { files: { id: number; name: string; source: string }[] };
    similar: { daiichi_patient_id: string; birth_year: number; prescriber: string }[];
  }>(`/${id}/records`, { signal });
export const fetchHistory = (id: string, signal?: AbortSignal) =>
  patientsFetch<{ items: { at: string | null; title: string; detail: string; review_id?: number; can_undo?: boolean }[] }>(
    `/${id}/history`,
    { signal },
  );
export const fetchRecord = (ref: string, signal?: AbortSignal) =>
  patientsFetch<{
    ref: string;
    source?: string;
    source_label: string;
    vendor_patient_id: string;
    reason: string;
    layer?: string | null;
    score?: number | null;
    score_items?: { label: string; points: number }[];
    rows: Record<string, string>[];
    daiichi_patient_id: string | null;
  }>(`/records/${ref}`, { signal });
export const fetchReviewQueue = (source: string, signal?: AbortSignal) =>
  patientsFetch<{
    items: ReviewItem[];
    counts: Record<string, number>;
    waiting: number;
    mapped_automatically_pct: number;
    assigned: number;
    top_suggestion_correct?: number | null;
    open_reviews?: number | null;
    thresholds: { auto: number; review: number; margin: number };
  }>(`/review${source ? `?source=${source}` : ''}`, { signal });
export const fetchReview = (id: number, signal?: AbortSignal) => patientsFetch<ReviewDetail>(`/review/${id}`, { signal });
export const assignReview = (id: number, daiichiPatientId: string) =>
  patientsFetch<{ daiichi_patient_id: string }>(`/review/${id}/assign`, {
    method: 'POST',
    body: JSON.stringify({ daiichi_patient_id: daiichiPatientId }),
  });
export const newReviewPatient = (id: number) => patientsFetch<{ daiichi_patient_id: string | null }>(`/review/${id}/new`, { method: 'POST' });
export const deferReview = (id: number) => patientsFetch<{ status: string }>(`/review/${id}/defer`, { method: 'POST' });
export const undoReview = (id: number) => patientsFetch<{ status: string }>(`/review/${id}/undo`, { method: 'POST' });
export const fetchAnalytics = (brand: string, payer: string, signal?: AbortSignal) => {
  const params = new URLSearchParams();
  if (brand && brand !== 'all') params.set('brand', brand);
  if (payer && payer !== 'all') params.set('payer', payer);
  const qs = params.toString();
  return patientsFetch<Analytics>(`/analytics${qs ? `?${qs}` : ''}`, { signal });
};
export const fetchPrivacy = (signal?: AbortSignal) => patientsFetch<Privacy>('/privacy', { signal });

export type Analytics = {
  banner: string | null;
  small_cell_min: number;
  kpis: Record<string, number | string | null>;
  funnel: { label: string; count: number | string; denominator?: number | string }[];
  never_reasons: { label: string; count: number | string }[];
  time_steps: { label: string; days: number | null }[];
  days_by_payer: { payer: string; days: number | null; patients: number | string }[];
  survival: { brand: string; description: string; at_6_months: number; points: number[][] }[];
  stops: { label: string; count: number | string }[];
  delay_causes: { label: string; count: number | string }[];
  prescribers: { doctor_id: string | null; name: string; patients: number | string; median_days: number | null; side_effect_stops: number | string }[];
  states: { state: string; patients: number | string; outside_hub: number | string }[];
  journeys: {
    id: string;
    brand: string;
    payer: string;
    sources: string[];
    linked_by: string;
    status: string;
    prescriber: string;
    doctor_id: string | null;
    stop_reason?: string;
    delayed?: boolean;
    in_hub?: boolean;
  }[];
};
export type Privacy = {
  received: Record<string, string>;
  layers: { layer: string; evidence: string; rule: string }[];
  roles: { role: string; vendor_ids: string; assign: string; journeys: string; dashboards: string }[];
  checks: { title: string; detail: string }[];
  audit: { at: string; actor: string; action: string; details: Record<string, unknown> }[];
  small_cell_min: number;
};
