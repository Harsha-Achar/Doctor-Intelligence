import type { ReviewCase } from '../../api/reviews';

export type StructuredSection = { key: string; heading: string; value: string };

export type StructuredReasoning = {
  structured?: boolean;
  valid?: boolean;
  queue_type?: string;
  recommendation_type?: 'approve_candidate' | 'hold' | 'needs_more_info' | 'reject';
  recommendation_label?: string;
  confidence?: string;
  confidence_reason?: string;
  recommended_doctor_id?: string | null;
  blocking_summary?: string;
  sections?: StructuredSection[];
};

const QUEUE_SECTION_HEADINGS: Record<string, string[]> = {
  compliance: ['Evidence', 'Blocking conflict', 'Alternate candidate', 'Missing evidence', 'Reviewer action', 'Recommendation'],
  identity: ['Score drivers', 'Conflicting fields', 'Alternates ruled out', 'Confirm before linking', 'Match decision'],
  unmatched: ['Score drivers', 'Conflicting fields', 'Alternates ruled out', 'Confirm before linking', 'Match decision'],
  safety: ['Risk signal', 'Source of signal', 'Clinical reviewer required', 'Hold status', 'Action'],
  proposed: ['Current value', 'Proposed value', 'Source of proposal', 'Risk if applied', 'Reviewer decision'],
  proposed_changes: ['Current value', 'Proposed value', 'Source of proposal', 'Risk if applied', 'Reviewer decision'],
};

const RECOMMENDATION_LABELS: Record<string, string> = {
  approve_candidate: 'Approve candidate',
  hold: 'Hold, do not link',
  needs_more_info: 'Needs more information',
  reject: 'Reject linking',
};

export function normalizeQueueType(queueType: string) {
  if (queueType === 'proposed') return 'proposed_changes';
  if (queueType === 'unmatched') return 'identity';
  return queueType;
}

export function isStructuredReasoning(reasoning: ReviewCase['reasoning']): reasoning is StructuredReasoning {
  return !!reasoning && reasoning.structured === true;
}

export function structuredReasoningValid(reasoning: ReviewCase['reasoning']): boolean {
  return isStructuredReasoning(reasoning) && reasoning.valid === true && Array.isArray(reasoning.sections);
}

const SUMMARY_SECTION_KEYS = new Set(['recommendation', 'match_decision', 'reviewer_decision', 'action']);

const MAX_SECTION_SENTENCES = 2;

function limitSentences(text: string, max: number): string {
  const matches = text.match(/[^.!?]+[.!?]+(\s|$)|[^.!?]+$/g);
  if (!matches || matches.length <= max) return text.trim();
  return matches
    .slice(0, max)
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export type ReasoningCandidateRef = {
  doctor_id?: string | null;
  name?: string | null;
  city?: string | null;
};

export function candidateDisplayLabel(candidate: ReasoningCandidateRef): string {
  const name = (candidate.name || '').trim() || 'Unnamed doctor';
  const city = (candidate.city || '').trim();
  return city ? `${name} · ${city}` : name;
}

export function humanizeReasoningText(text: string, candidates: ReasoningCandidateRef[]): string {
  let out = text;
  for (const row of candidates) {
    const id = row.doctor_id;
    if (!id) continue;
    const label = candidateDisplayLabel(row);
    out = out.split(id).join(label);
  }
  out = out.replace(/\bHCP-[A-F0-9]{4,}\b/gi, 'the alternate candidate');
  out = out.replace(/\bD\d{3,}\b/g, 'a listed candidate');
  return out;
}

const PLACEHOLDER_TEXT = new Set(['', 'none', 'not available', 'n/a', 'null', 'missing', 'unknown']);

export function isPlaceholderSectionValue(value: string | undefined | null): boolean {
  const raw = (value || '').trim();
  if (!raw) return true;
  const core = raw.replace(/[.!?,;:]+$/g, '').trim().toLowerCase();
  if (PLACEHOLDER_TEXT.has(core)) return true;
  if (/^none(\.|,|\s|$)/i.test(raw) && raw.length <= 12) return true;
  return false;
}

export function visibleReasoningSections<T extends StructuredSection>(
  sections: T[],
  candidates?: ReasoningCandidateRef[],
): T[] {
  return orderSectionsForDisplay(sections).filter((row) => {
    if (isPlaceholderSectionValue(row.value)) return false;
    const formatted = formatSectionText(row.value, row.key, candidates);
    return formatted !== 'Not available';
  });
}

export function formatSectionText(
  value: string | undefined | null,
  key?: string,
  candidates?: ReasoningCandidateRef[],
): string {
  let text = (value || '').trim();
  if (!text || PLACEHOLDER_TEXT.has(text.toLowerCase())) return 'Not available';
  if (candidates?.length) text = humanizeReasoningText(text, candidates);
  text = text.replace(/\brecord_snapshot\s+/gi, "This record's ");
  text = text.replace(/\bcandidate grid\s+/gi, 'The comparison table ');
  text = text.replace(/\bthe comparison table shows\b/gi, 'The table shows');
  text = text.replace(/\s{2,}/g, ' ');
  const maxSentences = key === 'reviewer_action' ? 1 : MAX_SECTION_SENTENCES;
  return limitSentences(text, maxSentences);
}

/** Puts recommendation-style sections last (for older cached LLM payloads). */
export function orderSectionsForDisplay<T extends { key: string }>(sections: T[]): T[] {
  const body: T[] = [];
  const summary: T[] = [];
  for (const row of sections) {
    if (SUMMARY_SECTION_KEYS.has(row.key)) summary.push(row);
    else body.push(row);
  }
  return [...body, ...summary];
}

export function expectedHeadings(queueType: string): string[] {
  const key = queueType === 'unmatched' ? 'unmatched' : queueType === 'proposed' ? 'proposed' : queueType;
  return QUEUE_SECTION_HEADINGS[key] || QUEUE_SECTION_HEADINGS.identity;
}

export function recommendationBadge(reasoning: StructuredReasoning): string {
  const label = reasoning.recommendation_label
    || RECOMMENDATION_LABELS[reasoning.recommendation_type || ''] 
    || 'Review required';
  const conf = (reasoning.confidence || 'medium').charAt(0).toUpperCase() + (reasoning.confidence || 'medium').slice(1);
  const why = reasoning.confidence_reason || 'Not available';
  return `${label} · Confidence: ${conf} (${why})`;
}

export function approveButtonDisabled(
  reasoning: ReviewCase['reasoning'],
  item: Pick<ReviewCase, 'link_blocked' | 'review_id'>,
  doctorId?: string | null,
): boolean {
  if (busyGuard(item)) return true;
  if (!structuredReasoningValid(reasoning) || !reasoning) return false;
  const rec = reasoning.recommendation_type;
  if (rec === 'hold' || rec === 'reject' || rec === 'needs_more_info') return true;
  if (rec === 'approve_candidate' && reasoning.recommended_doctor_id && doctorId !== reasoning.recommended_doctor_id) {
    return true;
  }
  return false;
}

function busyGuard(item: Pick<ReviewCase, 'link_blocked' | 'review_id'>) {
  return item.link_blocked || !item.review_id;
}

export function primaryApproveDoctorId(
  reasoning: ReviewCase['reasoning'],
  fallbackRecommended?: string | null,
): string | null | undefined {
  if (reasoning && structuredReasoningValid(reasoning) && reasoning.recommendation_type === 'approve_candidate') {
    return reasoning.recommended_doctor_id || fallbackRecommended;
  }
  return fallbackRecommended;
}

export function holdApprovalHint(
  reasoning: ReviewCase['reasoning'],
  candidates?: ReasoningCandidateRef[],
): string | null {
  if (!reasoning || !structuredReasoningValid(reasoning) || reasoning.recommendation_type !== 'hold') return null;
  let block = reasoning.blocking_summary || 'the blocking issue';
  if (candidates?.length) block = humanizeReasoningText(block, candidates);
  return `Approval is disabled until ${block} is resolved.`;
}

export function needsMoreInfoPrimary(reasoning: ReviewCase['reasoning']): boolean {
  return !!(reasoning && structuredReasoningValid(reasoning) && reasoning.recommendation_type === 'needs_more_info');
}
