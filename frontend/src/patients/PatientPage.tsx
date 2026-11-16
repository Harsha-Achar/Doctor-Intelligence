import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ErrorState } from '../components/ErrorState';
import { TableSkeleton } from '../components/Skeleton';
import {
  fetchDoses,
  fetchHistory,
  fetchPatient,
  fetchRecord,
  fetchRecords,
  fetchTimeline,
  undoReview,
  type RecordLink,
  type TimelineEvent,
} from './api';
import { Drawer, Icon, SRC, SourcePill, SummaryParagraph, fmt, layerName, shortDate, statusClass } from './widgets';

export function PatientPage() {
  const { patientId = '' } = useParams();
  const patient = useQuery({ queryKey: ['pt-patient', patientId], queryFn: ({ signal }) => fetchPatient(patientId, signal) });
  const records = useQuery({ queryKey: ['pt-records', patientId], queryFn: ({ signal }) => fetchRecords(patientId, signal) });
  const [tab, setTab] = useState<'timeline' | 'doses' | 'records' | 'history'>('timeline');
  const [ref, setRef] = useState<string | null>(null);
  if (patient.isLoading) return <TableSkeleton rows={4} />;
  if (patient.isError) return <ErrorState message="This patient could not be loaded." onRetry={() => patient.refetch()} />;
  if (!patient.data) return <p className="empty">Patient not found.</p>;
  const data = patient.data;
  const kpis = data.kpis;
  const oral = (kpis.unit || '').toLowerCase().includes('tablet') || data.brand === 'Brand C';
  const unit = oral ? 'fill' : 'dose';
  const stopped = data.status === 'Stopped';
  const never = data.status === 'Never started';
  const recordCount = data.record_count ?? records.data?.records.length;
  const tabs = [
    ['timeline', 'Timeline'],
    ['doses', `${oral ? 'Fills' : 'Doses'} (${kpis.dose_count ?? 0})`],
    ['records', `Source records${recordCount != null ? ` (${recordCount})` : ''}`],
    ['history', 'History'],
  ] as const;
  return (
    <div>
      <Link className="back" to="/patients/list">
        <Icon name="back" /> All patients
      </Link>
      <div className="card dhead">
        <div className="avatar"><Icon name="user" size={26} /></div>
        <div>
          <h2>
            <span className="mono" style={{ fontSize: 20 }}>{data.daiichi_patient_id}</span>{' '}
            <span className={`pill ${statusClass(data.status)}`} style={{ verticalAlign: 'middle' }}>{data.status}</span>
          </h2>
          <div className="dmeta">
            <span><b style={{ color: 'var(--fg)' }}>{data.brand}</b> · {data.description}</span>
            <span>Age {data.age_band} · {data.sex}</span>
            <span>{data.payer_type} insurance</span>
            <span>
              Prescriber{' '}
              {data.doctor_id ? <Link className="link" to={`/doctors/${data.doctor_id}`}>{data.prescriber}</Link> : data.prescriber}
            </span>
          </div>
          <div className="chips" style={{ marginTop: 8 }}>
            {['hub', 'pharmacy', 'claims'].filter((source) => data.sources.includes(source)).map((source) => <SourcePill key={source} source={source} />)}
            <span className="pill ok"><Icon name="shield" size={12} /> No identity received</span>
          </div>
        </div>
        <div className="acts">
          {data.pending_reviews.length ? (
            <Link className="btn" to={`/patients/review?case=${data.pending_reviews[0].review_id}`}>
              <Icon name="alert" />
              {data.pending_reviews.length} record{data.pending_reviews.length > 1 ? 's' : ''} to review
            </Link>
          ) : null}
        </div>
      </div>
      <div className="ai" id="ptSummary">
        <div className="ai-h">
          <b><Icon name="spark" size={14} /> AI summary</b>
          <span>What this patient is going through · data as of {data.as_of_label}</span>
        </div>
        {data.summary.paragraphs.map((paragraph) => (
          <SummaryParagraph key={paragraph} text={paragraph} onRef={setRef} />
        ))}
      </div>
      <div className="kpis k4">
        <div className="kpi">
          {stopped ? (
            <>
              <span className="lbl">Stopped on</span>
              <span className="val" style={{ fontSize: 22 }}>{kpis.stop_date_label || '—'}</span>
              <span className="sub">{kpis.stop_reason}</span>
            </>
          ) : (
            <>
              <span className="lbl">Next {unit} due</span>
              <span className="val" style={{ fontSize: 22 }}>{never || !kpis.next_dose_label ? '—' : kpis.next_dose_label}</span>
              <span className="sub">
                {kpis.dose_count ? (kpis.overdue ? <span className="pill warn">Overdue</span> : `Every ${oral ? '30 days' : '3 weeks'}`) : `No ${unit} yet`}
              </span>
            </>
          )}
        </div>
        <div className="kpi">
          <span className="lbl">Current dose</span>
          <span className="val" style={{ fontSize: 22 }}>{kpis.current_quantity != null ? `${kpis.current_quantity} × ${kpis.unit || ''}` : '—'}</span>
          <span className="sub">{kpis.current_quantity != null ? (oral ? 'Tablets per 30-day fill' : 'Vials per infusion') : 'No dose yet'}</span>
        </div>
        <div className="kpi">
          <span className="lbl">{oral ? 'Fills' : 'Doses'} received</span>
          <span className="val">{kpis.dose_count}</span>
          <span className="sub">{kpis.first_dose_label ? `Since ${kpis.first_dose_label}` : '—'}</span>
        </div>
        <div className="kpi" data-tour="pt-switch">
          <span className="lbl">Specialty pharmacy</span>
          <span className="val" style={{ fontSize: 17, lineHeight: 1.3 }}>{kpis.pharmacy || '—'}</span>
          <span className="sub">{kpis.previous_pharmacy ? `Switched from ${kpis.previous_pharmacy}` : kpis.pharmacy ? 'Same pharmacy throughout' : 'None linked'}</span>
        </div>
      </div>
      <div className="card">
        <div className="tabs" role="tablist">
          {tabs.map(([key, label]) => (
            <button key={key} className={`tab${tab === key ? ' on' : ''}`} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}>
              {label}
            </button>
          ))}
        </div>
        <div className="card-b pttab">
          {tab === 'timeline' ? <Timeline id={patientId} oral={oral} onRef={setRef} onDoses={() => setTab('doses')} /> : null}
          {tab === 'doses' ? <Doses id={patientId} oral={oral} onRef={setRef} /> : null}
          {tab === 'records' ? <Records id={patientId} onRef={setRef} /> : null}
          {tab === 'history' ? <History id={patientId} /> : null}
        </div>
      </div>
      {ref ? <RecordDrawer refId={ref} onClose={() => setRef(null)} /> : null}
    </div>
  );
}

function Timeline({ id, oral, onRef, onDoses }: { id: string; oral: boolean; onRef: (ref: string) => void; onDoses: () => void }) {
  const timeline = useQuery({ queryKey: ['pt-timeline', id], queryFn: ({ signal }) => fetchTimeline(id, signal) });
  const collapsed = useMemo(() => collapse(timeline.data?.events || []), [timeline.data]);
  if (timeline.isLoading) return <TableSkeleton />;
  if (timeline.isError) return <ErrorState message="The timeline could not be loaded." onRetry={() => timeline.refetch()} />;
  if (!timeline.data?.events.length) return <div className="empty"><b>No events</b></div>;
  let phase = '';
  return (
    <div className="timeline">
      {collapsed.map((item, index) => {
        const kind = 'events' in item ? 'dose' : item.kind;
        const nextPhase = kind === 'access' ? 'Getting access' : 'Treatment';
        const header = nextPhase !== phase ? nextPhase : null;
        phase = nextPhase;
        if ('events' in item) {
          const first = item.events[0];
          const last = item.events[item.events.length - 1];
          const qty = first.quantity;
          const unit = String(first.flags.unit || '');
          return (
            <div key={index}>
              {header ? <div className="tlphase">{header}</div> : null}
              <div className="tl">
                <span className="d">{shortDate(first.date_label)} – {shortDate(last.date_label)}</span>
                <span className="rail"><span className="node" style={{ background: SRC.pharmacy.color, color: '#fff' }}><Icon name="doc" size={12} /></span></span>
                <span className="body">
                  <b>{oral ? 'Fills' : 'Doses'} {String(first.flags.dose_index)}–{String(last.flags.dose_index)} · on schedule</b>
                  <span>
                    {item.events.length} {oral ? 'fills' : 'doses'}
                    {qty != null ? ` of ${qty} × ${unit}` : ''}
                    {first.pharmacy ? ` · ${first.pharmacy}` : ''}{' '}
                    <button className="link" type="button" onClick={onDoses}>See each {oral ? 'fill' : 'dose'}</button>
                  </span>
                </span>
              </div>
            </div>
          );
        }
        return (
          <div key={index}>
            {header ? <div className="tlphase">{header}</div> : null}
            <EventLine event={item} onRef={onRef} />
          </div>
        );
      })}
    </div>
  );
}

function EventLine({ event, onRef }: { event: TimelineEvent; onRef: (ref: string) => void }) {
  const warn = event.kind === 'stop' || event.flags.late || event.flags.reduced || (event.kind === 'note' && !event.flags.switch);
  const color = warn ? 'var(--warn)' : event.flags.switch ? 'var(--new)' : (SRC[event.source]?.color || 'var(--accent)');
  const icon = event.flags.switch ? 'move' : event.source === 'hub' ? 'users' : event.source === 'pharmacy' ? 'doc' : 'dollar';
  const oral = String(event.flags.unit || '').includes('tablet') || /fill/i.test(event.title);
  const title = event.kind === 'dose' && event.flags.dose_index
    ? (oral ? `Fill ${event.flags.dose_index} dispensed` : `Dose ${event.flags.dose_index} given`)
    : event.title;
  return (
    <div className={`tl${event.flags.uploaded ? ' isnew' : ''}`}>
      <span className="d">{event.date_label}</span>
      <span className="rail"><span className="node" style={{ background: color, color: '#fff' }}><Icon name={icon} size={12} /></span></span>
      <span className="body">
        <b>
          {title}
          {event.flags.uploaded ? <span className="pill new">New</span> : null}
        </b>
        <span>
          {event.detail} <span className="faint">· {event.source_label || SRC[event.source]?.label || event.source}</span>
          {event.ref ? <button className="cite" type="button" onClick={() => onRef(event.ref || '')}>{event.ref}</button> : null}
        </span>
      </span>
    </div>
  );
}

function collapse(events: TimelineEvent[]) {
  const out: (TimelineEvent | { events: TimelineEvent[] })[] = [];
  let run: TimelineEvent[] = [];
  const flush = () => {
    if (run.length >= 3) out.push({ events: run });
    else out.push(...run);
    run = [];
  };
  events.forEach((event) => {
    const onSchedule = event.kind === 'dose' && event.flags.on_schedule && !event.flags.late && !event.flags.reduced && !event.flags.uploaded;
    if (onSchedule) run.push(event);
    else {
      flush();
      out.push(event);
    }
  });
  flush();
  return out;
}

function Doses({ id, oral, onRef }: { id: string; oral: boolean; onRef: (ref: string) => void }) {
  const doses = useQuery({ queryKey: ['pt-doses', id], queryFn: ({ signal }) => fetchDoses(id, signal) });
  if (doses.isLoading) return <TableSkeleton />;
  if (doses.isError) return <ErrorState message="Doses could not be loaded." onRetry={() => doses.refetch()} />;
  if (!doses.data?.doses.length) return <div className="empty"><b>No doses yet</b><span>No dispense or claim is linked to this patient.</span></div>;
  return (
    <>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>{oral ? 'Fill' : 'Dose'}</th>
              <th>Date</th>
              <th>Quantity</th>
              <th>Pharmacy</th>
              <th>Claim</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {doses.data.doses.map((dose, index) => {
              const previous = index ? doses.data?.doses[index - 1] : undefined;
              const claimRef = typeof dose.flags.claim_ref === 'string' ? dose.flags.claim_ref : '';
              return (
                <tr key={`${dose.date}-${index}`}>
                  <td><b>{index + 1}</b></td>
                  <td style={{ whiteSpace: 'nowrap' }}>{dose.date_label}</td>
                  <td>{dose.quantity} × {String(dose.flags.unit || doses.data?.unit || '')}</td>
                  <td>
                    {dose.pharmacy || <span className="faint">—</span>}
                    {dose.ref ? <button className="cite" type="button" onClick={() => onRef(dose.ref || '')}>{dose.ref}</button> : null}
                  </td>
                  <td>
                    {dose.flags.claim_paid ? (
                      <>
                        <span className="pill ok">Paid</span>
                        {claimRef ? <button className="cite" type="button" onClick={() => onRef(claimRef)}>{claimRef}</button> : null}
                      </>
                    ) : (
                      <span className="faint">Not linked</span>
                    )}
                  </td>
                  <td>
                    {dose.flags.days_late ? <span className="pill warn">{String(dose.flags.days_late)} days late</span> : null}
                    {dose.flags.reduced ? <span className="pill neu">Reduced dose</span> : null}
                    {dose.flags.uploaded ? <span className="pill new">New file</span> : null}
                    {previous && previous.pharmacy && dose.pharmacy && previous.pharmacy !== dose.pharmacy ? <span className="pill new">New pharmacy</span> : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {doses.data.next_dose_label ? <p className="muted" style={{ margin: '12px 0 0' }}>Next {oral ? 'fill' : 'dose'} due <b>{doses.data.next_dose_label}</b>.</p> : null}
    </>
  );
}

function Records({ id, onRef }: { id: string; onRef: (ref: string) => void }) {
  const records = useQuery({ queryKey: ['pt-records', id], queryFn: ({ signal }) => fetchRecords(id, signal) });
  if (records.isLoading) return <TableSkeleton />;
  if (records.isError) return <ErrorState message="Source records could not be loaded." onRetry={() => records.refetch()} />;
  if (!records.data) return null;
  const groups = new Map<string, RecordLink[]>();
  records.data.records.forEach((record) => {
    const key = record.layer === 'first_record' ? 'First record' : layerName(record.layer);
    groups.set(key, [...(groups.get(key) || []), record]);
  });
  return (
    <div>
      <p className="muted" style={{ margin: '0 0 10px' }}>Where this patient's data came from. Click a record to see its rows as received.</p>
      <Lineage id={id} records={records.data.records} files={records.data.lineage.files || []} onRef={onRef} />
      <details className="how" style={{ marginTop: 12 }}>
        <summary>Why these records belong to one patient</summary>
        <div style={{ display: 'grid', gap: 14, marginTop: 10 }}>
          <div className="tw card" style={{ boxShadow: 'none' }}>
            <table>
              <thead>
                <tr><th>Matched by</th><th>Records</th><th>Evidence</th></tr>
              </thead>
              <tbody>
                {[...groups.entries()].map(([layer, rows]) => (
                  <tr key={layer}>
                    <td><b>{layer}</b></td>
                    <td>{rows.map((row) => <button key={row.ref} className="cite" type="button" onClick={() => onRef(row.ref)}>{row.ref}</button>)}</td>
                    <td className="muted">{[...new Set(rows.map((row) => row.reason).filter(Boolean))].join('; ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {records.data.records.filter((record) => record.score_items?.length).map((record) => (
            <div key={record.ref}>
              <h3 className="subh">Score for {record.ref}</h3>
              <ScoreTable items={record.score_items} total={record.score} />
            </div>
          ))}
          <div>
            <h3 className="subh">Similar patients kept separate</h3>
            {records.data.similar.length === 0 ? <p className="muted" style={{ margin: 0 }}>None.</p> : (
              <div className="list">
                {records.data.similar.map((item) => (
                  <Link key={item.daiichi_patient_id} className="li" to={`/patients/${item.daiichi_patient_id}`}>
                    <div className="ic neu"><Icon name="users" /></div>
                    <div className="tx"><b className="mono">{item.daiichi_patient_id}</b><span>Same prescriber, therapy and sex, born {item.birth_year} · nothing else in common</span></div>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>
      </details>
    </div>
  );
}

function ScoreTable({ items, total }: { items: { label: string; points: number }[]; total?: number | null }) {
  const sum = items.reduce((acc, item) => acc + item.points, 0);
  return (
    <div className="tw card" style={{ boxShadow: 'none' }}>
      <table>
        <tbody>
          {items.map((item, index) => (
            <tr key={index}><td>{item.label}</td><td className="n mono">{item.points > 0 ? `+${item.points}` : item.points}</td></tr>
          ))}
          <tr style={{ fontWeight: 600 }}><td>Total</td><td className="n mono">{total != null ? (total > 0 ? `+${total}` : total) : sum}</td></tr>
        </tbody>
      </table>
    </div>
  );
}

function Lineage({ id, records, files, onRef }: { id: string; records: RecordLink[]; files: { id: number; name: string; source: string }[]; onRef: (ref: string) => void }) {
  const ordered = [...records].sort((a, b) => a.source.localeCompare(b.source) || String(a.first_date).localeCompare(String(b.first_date)));
  const fileNodes = files.length
    ? files.map((file) => ({ key: String(file.id), source: file.source, name: file.name }))
    : [...new Set(ordered.map((record) => record.source))].map((source) => ({ key: source, source, name: SRC[source]?.label || source }));
  const layers = [...new Set(ordered.map((record) => (record.layer === 'first_record' ? 'First record' : layerName(record.layer))))];
  const rowH = 52;
  const H = Math.max(220, ordered.length * rowH + 40);
  const W = 980;
  const X = [10, 250, 520, 760];
  const yR = (index: number) => 34 + index * rowH + rowH / 2;
  const yS = (index: number, count: number) => 30 + ((H - 36) * (index + 0.5)) / count;
  const gY = H / 2 + 8;
  const fileY: Record<string, number> = {};
  fileNodes.forEach((file) => {
    const indexes = ordered.map((record, index) => (record.source === file.source ? index : -1)).filter((index) => index >= 0);
    fileY[file.key] = indexes.length ? (yR(indexes[0]) + yR(indexes[indexes.length - 1])) / 2 : 40;
  });
  const curve = (x1: number, y1: number, x2: number, y2: number) => `M${x1} ${y1} C${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}`;
  return (
    <div className="lineage">
      <svg viewBox={`0 0 ${W} ${H + 10}`} role="img" aria-label={`Lineage for ${id}`}>
        {['Source file', 'Vendor record', 'Matched by', 'Daiichi patient'].map((label, index) => (
          <text key={label} x={X[index]} y={14} className="s">{label.toUpperCase()}</text>
        ))}
        {ordered.map((record, index) => {
          const file = fileNodes.find((item) => item.source === record.source) || fileNodes[0];
          const layer = record.layer === 'first_record' ? 'First record' : layerName(record.layer);
          const y = yR(index);
          return <path key={`${record.ref}-a`} className="e" d={curve(X[0] + 220, file ? fileY[file.key] : 40, X[1], y)} />;
        })}
        {ordered.map((record, index) => {
          const layer = record.layer === 'first_record' ? 'First record' : layerName(record.layer);
          return <path key={`${record.ref}-b`} className="e" d={curve(X[1] + 230, yR(index), X[2], yS(layers.indexOf(layer), layers.length))} />;
        })}
        {layers.map((layer) => (
          <path key={layer} className="e" d={curve(X[2] + 190, yS(layers.indexOf(layer), layers.length), X[3], gY)} />
        ))}
        {fileNodes.map((file) => (
          <g key={file.key} className="nd src">
            <rect x={X[0]} y={fileY[file.key] - 20} width={220} height={40} rx={8} />
            <text x={X[0] + 10} y={fileY[file.key] - 3} fontWeight={600}>{SRC[file.source]?.label || file.source}</text>
            <text x={X[0] + 10} y={fileY[file.key] + 12} className="s">{file.name.length > 34 ? `${file.name.slice(0, 33)}…` : file.name}</text>
          </g>
        ))}
        {ordered.map((record, index) => {
          const y = yR(index);
          return (
            <g key={record.ref} className="nd" tabIndex={0} role="button" aria-label={record.ref} onClick={() => onRef(record.ref)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onRef(record.ref); } }}>
              <rect x={X[1]} y={y - 20} width={230} height={40} rx={7} />
              <text x={X[1] + 10} y={y - 3} className="mono">{record.ref}</text>
              <text x={X[1] + 10} y={y + 12} className="s">{record.source_label} · {record.vendor_patient_id}</text>
            </g>
          );
        })}
        {layers.map((layer) => (
          <g key={layer} className="nd dec">
            <rect x={X[2]} y={yS(layers.indexOf(layer), layers.length) - 18} width={190} height={36} rx={18} />
            <text x={X[2] + 95} y={yS(layers.indexOf(layer), layers.length) + 4} textAnchor="middle">{layer}</text>
          </g>
        ))}
        <g className="nd gold">
          <rect x={X[3]} y={gY - 40} width={200} height={80} rx={10} />
          <text x={X[3] + 14} y={gY - 14} fontWeight={700} className="mono">{id}</text>
          <text x={X[3] + 14} y={gY + 4} className="s">Daiichi patient ID</text>
          <text x={X[3] + 14} y={gY + 20} className="s">{records.length} records · {new Set(records.map((record) => record.source)).size} sources</text>
        </g>
      </svg>
    </div>
  );
}

function History({ id }: { id: string }) {
  const history = useQuery({ queryKey: ['pt-history', id], queryFn: ({ signal }) => fetchHistory(id, signal) });
  const client = useQueryClient();
  if (history.isLoading) return <TableSkeleton />;
  if (history.isError) return <ErrorState message="History could not be loaded." onRetry={() => history.refetch()} />;
  if (!history.data?.items.length) return <div className="empty"><b>No history yet</b></div>;
  return (
    <>
      <div className="list">
        {history.data.items.map((item, index) => (
          <div className="li" key={index}>
            <div className={`ic ${index ? 'ok' : 'acc'}`}><Icon name={item.can_undo ? 'review' : index ? 'check' : 'user'} /></div>
            <div className="tx">
              <b>{item.title}</b>
              <span>{item.detail}{item.at ? ` · ${item.at}` : ''}</span>
            </div>
            {item.can_undo && item.review_id ? (
              <button className="btn sm" type="button" onClick={() => void undoReview(item.review_id as number).then(() => {
                void client.invalidateQueries({ queryKey: ['pt-patient', id] });
                void client.invalidateQueries({ queryKey: ['pt-history', id] });
                void client.invalidateQueries({ queryKey: ['pt-review'] });
                void client.invalidateQueries({ queryKey: ['pt-overview'] });
              })}>Undo</button>
            ) : null}
          </div>
        ))}
      </div>
      <p className="muted" style={{ margin: '12px 0 0' }}>The AI summary is rebuilt whenever a record is added or a reviewer changes this patient.</p>
    </>
  );
}

export function RecordDrawer({ refId, onClose }: { refId: string; onClose: () => void }) {
  const record = useQuery({ queryKey: ['pt-record', refId], queryFn: ({ signal }) => fetchRecord(refId, signal), enabled: Boolean(refId) });
  const data = record.data;
  const columns = data?.rows[0] ? Object.keys(data.rows[0]) : [];
  return (
    <Drawer title={data ? `${data.ref} · ${data.source_label}` : refId} onClose={onClose} wide>
      {record.isLoading ? <p>Loading record…</p> : null}
      {record.isError ? <p className="empty">This record could not be opened.</p> : null}
      {data ? (
        <>
          <div className="chips">
            <SourcePill source={data.source || ''} />
            {data.daiichi_patient_id ? <Link className="link mono" to={`/patients/${data.daiichi_patient_id}`}>{data.daiichi_patient_id}</Link> : <span className="pill warn">Not yet mapped</span>}
          </div>
          <div className="card" style={{ boxShadow: 'none' }}>
            <div className="card-b">
              <dl className="kv">
                <dt>Vendor patient ID</dt><dd className="mono">{data.vendor_patient_id}</dd>
                <dt>Matched by</dt><dd>{data.layer ? layerName(data.layer) : 'Waiting'} · {data.reason}</dd>
              </dl>
            </div>
          </div>
          <div>
            <h3 className="subh">Rows as received ({data.rows.length})</h3>
            {data.rows.length === 0 ? <p className="empty">No raw rows stored.</p> : (
              <div className="tw card" style={{ boxShadow: 'none' }}>
                <table>
                  <thead><tr>{columns.map((column) => <th key={column} className="mono" style={{ fontSize: 11 }}>{column}</th>)}</tr></thead>
                  <tbody>
                    {data.rows.slice(0, 40).map((row, index) => (
                      <tr key={index}>{columns.map((column) => <td key={column} className="mono" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{row[column]}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          {data.score_items?.length ? (
            <div>
              <h3 className="subh">Score breakdown</h3>
              <ScoreTable items={data.score_items} total={data.score} />
            </div>
          ) : null}
        </>
      ) : null}
    </Drawer>
  );
}
