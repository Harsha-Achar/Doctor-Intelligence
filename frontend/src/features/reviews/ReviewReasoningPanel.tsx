import type { ReviewCase } from '../../api/reviews';
import {
  formatSectionText,
  structuredReasoningValid,
  visibleReasoningSections,
  type StructuredReasoning,
} from './reviewReasoning';

const FALLBACK = 'Reasoning unavailable, manual review required';

const SUMMARY_KEYS = new Set(['recommendation', 'match_decision', 'reviewer_decision', 'action']);

type Props = {
  queueType: string;
  reasoning: ReviewCase['reasoning'];
  candidates?: ReviewCase['candidates'];
  busy?: boolean;
  failed?: boolean;
};

export function ReviewReasoningPanel({ queueType, reasoning, candidates, busy, failed }: Props) {
  void queueType;
  if (busy) {
    return <p className="muted" style={{ margin: 0 }}>Generating comparison…</p>;
  }
  if (failed || (reasoning && !structuredReasoningValid(reasoning))) {
    return <p className="muted" style={{ margin: 0 }}>{FALLBACK}</p>;
  }
  if (!reasoning || !structuredReasoningValid(reasoning)) {
    return null;
  }
  const structured = reasoning as StructuredReasoning;
  const sections = visibleReasoningSections(structured.sections || [], candidates);
  if (!sections.length) {
    return <p className="muted" style={{ margin: 0 }}>{FALLBACK}</p>;
  }
  return (
    <div className="reason">
      <h4>AI reasoning · recommendation only</h4>
      <ul className="reason-bullets">
        {sections.map((row, index) => {
          const isSummary = SUMMARY_KEYS.has(row.key);
          const isLast = index === sections.length - 1;
          const text = formatSectionText(row.value, row.key, candidates);
          return (
            <li
              key={row.key}
              className={isSummary && isLast ? 'reason-step' : undefined}
            >
              <b>{row.heading}</b>
              <span className="muted"> — </span>
              {text}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export { FALLBACK as reasoningFallbackMessage };
