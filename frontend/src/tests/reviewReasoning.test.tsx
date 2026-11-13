import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ReviewCase } from '../api/reviews';
import { ReviewReasoningPanel } from '../features/reviews/ReviewReasoningPanel';
import {
  approveButtonDisabled,
  expectedHeadings,
  formatSectionText,
  holdApprovalHint,
  humanizeReasoningText,
  isPlaceholderSectionValue,
  visibleReasoningSections,
} from '../features/reviews/reviewReasoning';

function complianceP3305Reasoning(): NonNullable<ReviewCase['reasoning']> {
  return {
    structured: true,
    valid: true,
    recommendation_type: 'hold',
    recommendation_label: 'Hold, do not link',
    confidence: 'low',
    confidence_reason: 'conflicting identifier',
    blocking_summary: 'The NPI field is conflicting for William Harris Jr versus William Harris Sr.',
    sections: [
      { key: 'evidence', heading: 'Evidence', value: 'Name field matches William Harris Jr.' },
      {
        key: 'blocking_conflict',
        heading: 'Blocking conflict',
        value: 'The NPI field is conflicting for William Harris Jr versus William Harris Sr.',
      },
      { key: 'alternate_candidate', heading: 'Alternate candidate', value: 'William Harris Sr scores 0.51.' },
      { key: 'missing_evidence', heading: 'Missing evidence', value: 'None' },
      { key: 'reviewer_action', heading: 'Reviewer action', value: 'Check NPI 1500605765 against the NPPES registry.' },
      { key: 'recommendation', heading: 'Recommendation', value: 'Hold payment approval.' },
    ],
  };
}

describe('review reasoning headings', () => {
  it.each([
    ['compliance', 'Evidence'],
    ['identity', 'Score drivers'],
    ['safety', 'Risk signal'],
    ['proposed', 'Current value'],
    ['unmatched', 'Score drivers'],
  ] as const)('queue %s starts with %s', (queue, first) => {
    expect(expectedHeadings(queue)[0]).toBe(first);
  });
});

describe('ReviewReasoningPanel', () => {
  it('renders compliance sections in order', () => {
    render(
      <ReviewReasoningPanel queueType="compliance" reasoning={complianceP3305Reasoning()} />,
    );
    expect(screen.getByText('Evidence')).toBeInTheDocument();
    expect(screen.getByText('Hold payment approval.')).toBeInTheDocument();
    expect(screen.queryByText(/Approve candidate · Confidence/)).not.toBeInTheDocument();
  });

  it('shows fallback for malformed structured payload', () => {
    render(
      <ReviewReasoningPanel
        queueType="compliance"
        reasoning={{ structured: true, valid: false, sections: [{ key: 'x', heading: 'X', value: 'raw' }] }}
      />,
    );
    expect(screen.getByText('Reasoning unavailable, manual review required')).toBeInTheDocument();
    expect(screen.queryByText('raw')).not.toBeInTheDocument();
  });

  it('hides sections with no information', () => {
    const reasoning = complianceP3305Reasoning();
    reasoning.sections = reasoning.sections!.map((row) =>
      row.key === 'missing_evidence' ? { ...row, value: 'None' } : row,
    );
    render(<ReviewReasoningPanel queueType="compliance" reasoning={reasoning} />);
    expect(screen.queryByText('Missing evidence')).not.toBeInTheDocument();
    expect(screen.getByText('Recommendation')).toBeInTheDocument();
  });
});

describe('placeholder sections', () => {
  it('treats None and Not available as empty', () => {
    expect(isPlaceholderSectionValue('None')).toBe(true);
    expect(isPlaceholderSectionValue('None.')).toBe(true);
    expect(isPlaceholderSectionValue('Not available')).toBe(true);
    expect(isPlaceholderSectionValue('NPI field matches.')).toBe(false);
  });

  it('filters empty boxes from display', () => {
    const sections = [
      { key: 'score_drivers', heading: 'Score drivers', value: 'NPI matches.' },
      { key: 'confirm_before_linking', heading: 'Confirm before linking', value: 'None' },
      { key: 'match_decision', heading: 'Match decision', value: 'Link to John Smith.' },
    ];
    const visible = visibleReasoningSections(sections);
    expect(visible.map((r) => r.key)).toEqual(['score_drivers', 'match_decision']);
  });
});

describe('humanize internal ids', () => {
  it('replaces HCP ids with candidate names', () => {
    const candidates = [
      { doctor_id: 'HCP-950CA2E4', name: 'William Harris Jr', city: 'Boston' },
      { doctor_id: 'HCP-566528CD', name: 'William Harris Sr', city: 'Boston' },
    ];
    const text = humanizeReasoningText('Approve HCP-950CA2E4; HCP-566528CD conflicts.', candidates);
    expect(text).not.toMatch(/HCP-/);
    expect(text).toContain('William Harris Jr · Boston');
    expect(formatSectionText('Match to HCP-950CA2E4', 'evidence', candidates)).toContain('William Harris Jr');
  });
});

describe('P-3305 hold behavior', () => {
  const item = { link_blocked: false, review_id: 'REV-1' };
  const reasoning = complianceP3305Reasoning();

  it('disables approve buttons on hold', () => {
    expect(approveButtonDisabled(reasoning, item, 'D004')).toBe(true);
    expect(approveButtonDisabled(reasoning, item, 'D005')).toBe(true);
  });

  it('shows hold approval hint', () => {
    expect(holdApprovalHint(reasoning)).toMatch(/Approval is disabled until/);
  });

  it('does not use points to in blocking conflict copy', () => {
    const conflict = reasoning.sections!.find((row) => row.key === 'blocking_conflict')!.value;
    expect(conflict.toLowerCase()).not.toContain('points to');
  });
});
