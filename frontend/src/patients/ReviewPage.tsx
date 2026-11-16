import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ErrorState } from '../components/ErrorState';
import { TableSkeleton } from '../components/Skeleton';
import { assignReview, deferReview, fetchPatient, fetchRecords, fetchReview, fetchReviewQueue, newReviewPatient, type ReviewDetail } from './api';
import { Drawer, Icon, SRC, SourcePill, Toast, fmt, sgn, statusClass } from './widgets';

export function ReviewPage() {
  const [params, setParams] = useSearchParams();
  const source = params.get('source') || '';
  const queue = useQuery({ queryKey: ['pt-review', source], queryFn: ({ signal }) => fetchReviewQueue(source, signal) });
  const selected = Number(params.get('case') || queue.data?.items[0]?.id || 0);
  const detail = useQuery({
    queryKey: ['pt-review-case', selected],
    queryFn: ({ signal }) => fetchReview(selected, signal),
    enabled: selected > 0,
  });
  const [toast, setToast] = useState<ReactNode>(null);
  const [drawer, setDrawer] = useState<string | null>(null);
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ['pt-review'] });
    void client.invalidateQueries({ queryKey: ['pt-overview'] });
    void client.invalidateQueries({ queryKey: ['pt-patients'] });
    void client.invalidateQueries({ queryKey: ['pt-patient'] });
  };
  function selectNext(id: number) {
    const items = queue.data?.items || [];
    const index = items.findIndex((item) => item.id === id);
    const next = items[index + 1] || items[index - 1];
    const nextParams: Record<string, string> = {};
    if (source) nextParams.source = source;
    if (next) nextParams.case = String(next.id);
    setParams(nextParams);
  }
  const act = useMutation({
    mutationFn: async (action: { type: 'assign'; id: number; patient: string } | { type: 'new' | 'defer'; id: number }) => {
      if (action.type === 'assign') return assignReview(action.id, action.patient);
      if (action.type === 'new') return newReviewPatient(action.id);
      return deferReview(action.id);
    },
    onSuccess: (result, action) => {
      selectNext(action.id);
      refresh();
      if (action.type === 'assign') {
        setToast(
          <>
            Assigned to {action.patient} · journey updated{' '}
            <Link className="link" to={`/patients/${action.patient}`}>View patient</Link>
          </>,
        );
      } else if (action.type === 'new') {
        const id = result && 'daiichi_patient_id' in result ? result.daiichi_patient_id : null;
        setToast(
          <>
            Created a new Daiichi patient ID
            {id ? <> <Link className="link" to={`/patients/${id}`}>{id}</Link></> : null}
          </>,
        );
      } else {
        setToast(<>Deferred · stays in the queue</>);
      }
    },
  });
  const data = queue.data;
  const topRight = data?.top_suggestion_correct;
  const openReviews = data?.open_reviews;
  const suggestion = topRight != null && openReviews ? `${Math.round((100 * topRight) / Math.max(1, openReviews))}%` : '—';

  return (
    <div data-tour="pt-review">
      {queue.isLoading ? <TableSkeleton rows={3} /> : null}
      {queue.isError ? <ErrorState message="The review queue could not be loaded." onRetry={() => queue.refetch()} /> : null}
      {data ? (
        <div className="kpis k4">
          <div className="kpi">
            <span className="lbl">Waiting to be mapped</span>
            <span className="val">{data.waiting}</span>
            <span className="sub">Score between +{data.thresholds.review} and +{data.thresholds.auto}, or two patients too close to call</span>
          </div>
          <div className="kpi">
            <span className="lbl">Mapped automatically</span>
            <span className="val">{data.mapped_automatically_pct}%</span>
            <span className="sub">Of all source records</span>
          </div>
          <div className="kpi">
            <span className="lbl">Assigned by reviewers</span>
            <span className="val">{data.assigned}</span>
            <span className="sub">This session · every decision logged and reversible</span>
          </div>
          <div className="kpi">
            <span className="lbl">Top suggestion is right</span>
            <span className="val">{suggestion}</span>
            <span className="sub">Measured on the synthetic answer key</span>
          </div>
        </div>
      ) : null}
      <div className="banner warn">
        <Icon name="shield" />
        Decisions use de-identified evidence only: program IDs, birth year, sex, ZIP3, prescriber, product, payer and dates. No names are received or shown.
      </div>
      <div className="rv">
        <div className="card queue">
          <div className="card-h">
            <h2>Not yet mapped</h2>
            <span className="hint">{data?.waiting ?? 0} records</span>
          </div>
          <div className="card-b" style={{ paddingBottom: 10 }}>
            <div className="chips">
              {[['', 'All', 'all'], ['claims', 'Claims', 'claims'], ['pharmacy', 'Pharmacy', 'pharmacy'], ['hub', 'Hub', 'hub']].map(([value, label, key]) => (
                <button key={key} className={`chip${source === value ? ' on' : ''}`} type="button" onClick={() => setParams(value ? { source: value } : {})}>
                  {label}<span className="c">{data?.counts[key] ?? ''}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="qlist">
            {data && data.items.length === 0 ? <div className="empty"><b>All mapped</b><span>No low-confidence records waiting.</span></div> : null}
            {data?.items.map((item) => (
              <button
                key={item.id}
                className={`qi${selected === item.id ? ' on' : ''}`}
                type="button"
                onClick={() => setParams(source ? { source, case: String(item.id) } : { case: String(item.id) })}
              >
                <b>Which Daiichi patient is {item.source_label.toLowerCase()} patient {item.vendor_patient_id}?</b>
                <span className="m">
                  <span className="pill warn">Best {sgn(item.best_score)}</span>
                  <span>1 record</span>
                  <span>· {item.candidates || 0} candidate{(item.candidates || 0) === 1 ? '' : 's'}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
        <div style={{ display: 'grid', gap: 16, minWidth: 0 }}>
          {selected === 0 ? <div className="card"><div className="empty"><Icon name="check" /><b>Nothing selected</b><span>Pick a record from the list.</span></div></div> : null}
          {detail.isLoading ? <TableSkeleton /> : null}
          {detail.isError ? <ErrorState message="This case could not be loaded." onRetry={() => detail.refetch()} /> : null}
          {detail.data ? (
            <Case
              detail={detail.data}
              pending={act.isPending}
              onAssign={(patient) => act.mutate({ type: 'assign', id: detail.data.id, patient })}
              onNew={() => act.mutate({ type: 'new', id: detail.data.id })}
              onDefer={() => act.mutate({ type: 'defer', id: detail.data.id })}
              onView={setDrawer}
            />
          ) : null}
          {act.isError ? <ErrorState message={act.error instanceof Error ? act.error.message : 'The decision was not saved.'} /> : null}
        </div>
      </div>
      {toast ? <Toast onDone={() => setToast(null)}>{toast}</Toast> : null}
      {drawer ? <QuickPatient id={drawer} onClose={() => setDrawer(null)} /> : null}
    </div>
  );
}

function evidencePhrases(candidate: ReviewDetail['candidates'][number] | undefined, ...tones: string[]) {
  return (candidate?.evidence || [])
    .filter((row) => tones.includes(row.candidate?.tone))
    .map((row) => {
      if (row.field === 'ZIP3') return 'ZIP3';
      if (row.field === 'Program IDs') return 'program IDs';
      if (row.field === 'Dates line up') return 'dates';
      return row.field.toLowerCase();
    });
}

function Case({
  detail,
  pending,
  onAssign,
  onNew,
  onDefer,
  onView,
}: {
  detail: ReviewDetail;
  pending: boolean;
  onAssign: (id: string) => void;
  onNew: () => void;
  onDefer: () => void;
  onView: (id: string) => void;
}) {
  const record = detail.record;
  const program = [...(record.hub_case_ids || []), ...(record.copay_card_ids || [])];
  const reasoning = detail.reasoning;
  const best = detail.candidates[0];
  const idLabel = record.source === 'hub' ? 'Hub patient ID' : record.source === 'pharmacy' ? 'Pharmacy patient ID' : record.source === 'claims' ? 'Claims vendor patient ID' : 'Vendor patient ID';
  const agrees = reasoning.agrees?.length ? reasoning.agrees : evidencePhrases(best, 'y');
  const differs = reasoning.differs?.length ? reasoning.differs : evidencePhrases(best, 'n', 'p', 'm');
  const next = reasoning.what_happens_next === 'Assigning links this record to the Daiichi patient and rebuilds the journey. A person can undo it.'
    ? "Assigning adds this record to the Daiichi patient and their journey. It can be undone from the patient's history."
    : reasoning.what_happens_next;
  return (
    <>
      <div className="card">
        <div className="card-b" style={{ display: 'grid', gap: 12 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="pill warn">Low confidence</span>
            <SourcePill source={record.source || ''} />
            <span className="mono faint">{record.ref}</span>
          </div>
          <h2 style={{ margin: 0, fontSize: 19 }}>Which Daiichi patient is this {record.source_label.toLowerCase()} patient?</h2>
          <div className="rec">
            <div><span>{idLabel}</span><b className="mono">{record.vendor_patient_id}</b></div>
            <div><span>Records</span>{record.row_count ?? 1}</div>
            <div><span>Birth year</span>{record.birth_year}</div>
            <div><span>Sex</span>{record.sex}</div>
            <div><span>ZIP3</span>{record.zip3}</div>
            <div><span>Prescriber</span>{record.doctor_id ? <Link className="link" to={`/doctors/${record.doctor_id}`}>{record.prescriber}</Link> : record.prescriber}</div>
            <div><span>Product</span>{record.brand}</div>
            <div><span>Payer</span>{record.payer_type}</div>
            <div><span>First date</span>{record.first_date_label || '—'}</div>
            <div><span>Program IDs</span>{program.length ? program.join(', ') : 'none'}</div>
          </div>
        </div>
      </div>
      <div className="card">
        <div className="card-h">
          <h3>{detail.candidates.length} nearest Daiichi patient{detail.candidates.length === 1 ? '' : 's'}</h3>
          <span className="hint">Ranked by Splink score</span>
        </div>
        <div className="card-b">
          <div className="cands">
            {detail.candidates.map((candidate) => {
              const color = candidate.score >= 10 ? 'var(--ok)' : candidate.score >= 3 ? 'var(--warn)' : 'var(--neu)';
              return (
                <div key={candidate.daiichi_patient_id} className={`cand${candidate.suggested ? ' on' : ''}`}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                    <b className="mono">{candidate.daiichi_patient_id}</b>
                    {candidate.suggested ? <span className="pill ok">Suggested</span> : null}
                  </div>
                  {candidate.profile ? (
                    <>
                      <span className="muted">Born {candidate.profile.birth_year ?? '—'} · {candidate.profile.sex || '—'} · ZIP3 {candidate.profile.zip3 || '—'}</span>
                      <span className="muted">{candidate.profile.sources.map((item) => SRC[item]?.label || item).join(', ')} · {candidate.profile.record_count} record{candidate.profile.record_count === 1 ? '' : 's'}</span>
                    </>
                  ) : <span className="muted">Profile unavailable</span>}
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                    <span className="score" style={{ color }}>{sgn(candidate.score)}</span>
                    <span className="muted">points · {Math.round(candidate.probability * 100)}% match probability</span>
                  </div>
                  <div className="meter"><i style={{ width: `${Math.round(candidate.probability * 100)}%`, background: color }} /></div>
                  <div className="chips">
                    <button className={`btn sm${candidate.suggested ? ' primary' : ''}`} type="button" disabled={pending} onClick={() => onAssign(candidate.daiichi_patient_id)}>Assign</button>
                    <button className="btn sm ghost" type="button" onClick={() => onView(candidate.daiichi_patient_id)}>View patient</button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <div className="card">
        <div className="card-h">
          <h3>Evidence comparison</h3>
          <span className="hint">✓ same · ≈ partly · ✗ different · — not available</span>
        </div>
        <div className="card-b tw">
          <table className="cmp">
            <thead>
              <tr>
                <th>Evidence</th>
                <th>This record</th>
                {detail.candidates.map((candidate) => <th key={candidate.daiichi_patient_id} className="mono">{candidate.daiichi_patient_id}</th>)}
              </tr>
            </thead>
            <tbody>
              {(best?.evidence || []).map((row, index) => (
                <tr key={row.field}>
                  <td className="muted">{row.field}</td>
                  <td>{row.record ?? '—'}</td>
                  {detail.candidates.map((candidate) => {
                    const cell = candidate.evidence[index]?.candidate;
                    return (
                      <td key={candidate.daiichi_patient_id} className="v">
                        {cell ? <><span className={`sym ${cell.tone}`}>{cell.symbol}</span>{cell.text}</> : '—'}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="card">
        <div className="card-b" style={{ display: 'grid', gap: 12 }}>
          <div className="reason">
            <h4><Icon name="spark" size={13} /> AI reasoning · recommendation only</h4>
            <p style={{ margin: 0 }}><b>Our recommendation:</b> {reasoning.recommendation}</p>
            <p style={{ margin: 0 }}><b>Why it wasn't mapped automatically:</b> {reasoning.why_not_auto}</p>
            <p style={{ margin: 0 }}><b>What agrees{best ? ` with ${best.daiichi_patient_id}` : ''}:</b> {agrees.join(', ') || 'nothing'}. <b>Different or missing:</b> {differs.join(', ') || 'nothing'}.</p>
            {reasoning.why_not_others ? <p style={{ margin: 0 }}><b>Why not the others:</b> {reasoning.why_not_others}</p> : null}
            <p style={{ margin: 0 }}><b>What happens next:</b> {next}</p>
            {best?.items?.length ? (
              <details className="how">
                <summary>Score breakdown for {best.daiichi_patient_id}</summary>
                <div className="tw card" style={{ boxShadow: 'none' }}>
                  <table>
                    <tbody>
                      {best.items.map((item, index) => (
                        <tr key={index}><td>{item.label}</td><td className="n mono">{item.points > 0 ? `+${item.points}` : item.points}</td></tr>
                      ))}
                      <tr style={{ fontWeight: 600 }}><td>Total</td><td className="n mono">{sgn(best.score)}</td></tr>
                    </tbody>
                  </table>
                </div>
              </details>
            ) : null}
          </div>
          <div className="chips">
            <button className="btn" type="button" disabled={pending} onClick={onNew}>None of these · create new Daiichi patient ID</button>
            <button className="btn ghost" type="button" disabled={pending} onClick={onDefer}>Defer</button>
          </div>
        </div>
      </div>
    </>
  );
}

function QuickPatient({ id, onClose }: { id: string; onClose: () => void }) {
  const patient = useQuery({ queryKey: ['pt-patient', id], queryFn: ({ signal }) => fetchPatient(id, signal) });
  const records = useQuery({ queryKey: ['pt-records', id], queryFn: ({ signal }) => fetchRecords(id, signal) });
  const data = patient.data;
  return (
    <Drawer title={`Patient ${id}`} onClose={onClose}>
      {patient.isLoading ? <p>Loading patient…</p> : null}
      {patient.isError ? <p className="empty">This patient could not be opened.</p> : null}
      {data ? (
        <>
          <div className="chips">
            <span className="pill ok"><Icon name="shield" size={12} /> No identity received</span>
            <span className={`pill ${statusClass(data.status)}`}>{data.status}</span>
            {['hub', 'pharmacy', 'claims'].filter((source) => data.sources.includes(source)).map((source) => <SourcePill key={source} source={source} />)}
          </div>
          <div className="card" style={{ boxShadow: 'none' }}>
            <div className="card-b">
              <dl className="kv">
                <dt>Age band · sex</dt><dd>{data.age_band} · {data.sex}</dd>
                <dt>Brand</dt><dd>{data.brand} · {data.description}</dd>
                <dt>Prescriber</dt><dd>{data.doctor_id ? <Link className="link" to={`/doctors/${data.doctor_id}`}>{data.prescriber}</Link> : data.prescriber}</dd>
                <dt>Payer type</dt><dd>{data.payer_type}</dd>
              </dl>
            </div>
          </div>
          <div>
            <h3 className="subh">Linked records</h3>
            <div className="tw card" style={{ boxShadow: 'none' }}>
              <table>
                <thead><tr><th>Record</th><th>Source</th><th>Vendor patient ID</th><th>Matched by</th></tr></thead>
                <tbody>
                  {records.data?.records.map((record) => (
                    <tr key={record.ref}>
                      <td className="mono">{record.ref}</td>
                      <td>{record.source_label}</td>
                      <td className="mono">{record.vendor_patient_id}</td>
                      <td>{record.layer}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <Link className="btn primary" to={`/patients/${id}`} style={{ justifySelf: 'start' }}>Open full patient page</Link>
        </>
      ) : null}
    </Drawer>
  );
}
