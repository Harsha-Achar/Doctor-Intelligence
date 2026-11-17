import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ErrorState } from '../components/ErrorState';
import { TableSkeleton } from '../components/Skeleton';
import { fetchPatients } from './api';
import { MappingModal } from './MappingModal';
import { SourceDots, fmt, statusClass } from './widgets';

const FILTERS: { id: string; label: string; status?: string; switched?: boolean; pending?: boolean }[] = [
  { id: 'all', label: 'All' },
  { id: 'On therapy', label: 'On therapy', status: 'On therapy' },
  { id: 'Waiting to start', label: 'Waiting to start', status: 'Waiting to start' },
  { id: 'Stopped', label: 'Stopped', status: 'Stopped' },
  { id: 'Never started', label: 'Never started', status: 'Never started' },
  { id: 'switched', label: 'Switched pharmacy', switched: true },
  { id: 'pending', label: 'Possible record pending', pending: true },
];

export function PatientsPage() {
  const [filter, setFilter] = useState('all');
  const [q, setQ] = useState('');
  const [mapOpen, setMapOpen] = useState(false);
  const chosen = FILTERS.find((item) => item.id === filter) || FILTERS[0];
  const params = new URLSearchParams({ page: '1', page_size: '100' });
  if (chosen.status) params.set('status', chosen.status);
  if (chosen.switched) params.set('switched', 'true');
  if (chosen.pending) params.set('pending', 'true');
  if (q.trim()) params.set('q', q.trim());
  const query = params.toString();
  const list = useQuery({ queryKey: ['pt-patients', query], queryFn: ({ signal }) => fetchPatients(query, signal) });
  const countsQuery = useQuery({
    queryKey: ['pt-patients', 'counts'],
    queryFn: ({ signal }) => fetchPatients('page=1&page_size=1', signal),
  });
  const navigate = useNavigate();
  const counts = countsQuery.data?.counts || list.data?.counts;
  const countFor = useMemo(() => {
    return (id: string) => {
      if (!counts) return '';
      if (id === 'all') return counts.all;
      if (id === 'switched') return counts.switched;
      if (id === 'pending') return counts.pending;
      return counts[id] ?? '';
    };
  }, [counts]);
  const asOf = list.data?.as_of_label || countsQuery.data?.as_of_label;

  return (
    <div className="stack">
      {list.isLoading ? <TableSkeleton rows={4} /> : null}
      {list.isError ? <ErrorState message="Patients could not be loaded." onRetry={() => list.refetch()} /> : null}
      <div className="kpis k5">
        <button className="kpi" type="button" onClick={() => setFilter('all')}>
          <span className="lbl">Patients</span>
          <span className="val">{fmt(counts?.all)}</span>
          <span className="sub">One Daiichi patient ID each</span>
        </button>
        <button className="kpi" type="button" onClick={() => setFilter('On therapy')}>
          <span className="lbl">On therapy now</span>
          <span className="val" style={{ color: 'var(--ok)' }}>{fmt(counts?.['On therapy'])}</span>
          <span className="sub">{asOf ? `As of ${asOf}` : 'Current status'}</span>
        </button>
        <button className="kpi" type="button" onClick={() => setFilter('Waiting to start')}>
          <span className="lbl">Waiting to start</span>
          <span className="val">{fmt(counts?.['Waiting to start'])}</span>
          <span className="sub">Enrolled, no dose yet</span>
        </button>
        <button className="kpi" type="button" data-tour="pt-switch" onClick={() => setFilter('switched')}>
          <span className="lbl">Switched pharmacy</span>
          <span className="val">{fmt(counts?.switched)}</span>
          <span className="sub">Same patient, new pharmacy</span>
        </button>
        <button className="kpi" type="button" onClick={() => setMapOpen(true)}>
          <span className="lbl">Mapped automatically</span>
          <span className="val">{list.data?.mapped_automatically_pct ?? countsQuery.data?.mapped_automatically_pct ?? '—'}%</span>
          <span className="sub">How records were mapped →</span>
        </button>
      </div>
      <div className="card">
        <div className="card-b filterbar">
          <div className="chips">
            {FILTERS.map((item) => (
              <button key={item.id} className={`chip${filter === item.id ? ' on' : ''}`} type="button" onClick={() => setFilter(item.id)}>
                {item.label}
                {countFor(item.id) === '' ? null : <span className="c">{fmt(countFor(item.id))}</span>}
              </button>
            ))}
          </div>
          <input className="idsearch" aria-label="Search patient ID" placeholder="Search Daiichi or vendor ID" value={q} onChange={(event) => setQ(event.target.value)} />
        </div>
      </div>
      <div className="card tw" data-tour="pt-patients">
        <table>
          <thead>
            <tr>
              <th>Patient</th>
              <th>Therapy</th>
              <th>Status</th>
              <th>Next dose</th>
              <th>Prescriber</th>
              <th>Pharmacy</th>
              <th>Data from</th>
            </tr>
          </thead>
          <tbody>
            {list.data && list.data.items.length === 0 ? (
              <tr><td colSpan={7} className="muted">No patients match.</td></tr>
            ) : null}
            {list.data?.items.map((row) => (
              <tr key={row.daiichi_patient_id} className="click" onClick={() => navigate(`/patients/${row.daiichi_patient_id}`)}>
                <td>
                  <b className="mono">{row.daiichi_patient_id}</b>
                  {row.pending ? <span className="pill warn">Review</span> : null}
                  <div className="faint" style={{ fontSize: 12 }}>{row.age_band} · {row.sex} · {row.payer_type}</div>
                </td>
                <td>
                  {row.brand}
                  <div className="faint" style={{ fontSize: 12 }}>{row.description}</div>
                </td>
                <td><span className={`pill ${statusClass(row.status)}`}>{row.status}</span></td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  {row.status === 'Stopped' && row.stop_date_label ? (
                    <span className="faint">Stopped {row.stop_date_label}</span>
                  ) : row.next_dose_label ? (
                    <>
                      <b>{row.next_dose_label}</b>
                      {row.overdue ? <span className="pill warn">Overdue</span> : null}
                    </>
                  ) : (
                    <span className="faint">—</span>
                  )}
                </td>
                <td>{row.prescriber}</td>
                <td>
                  {row.pharmacy ? (
                    <>
                      {row.pharmacy}
                      {row.switched ? <span className="pill neu" title={row.previous_pharmacy ? `Previously ${row.previous_pharmacy}` : 'Switched pharmacy'}>Switched</span> : null}
                    </>
                  ) : (
                    <span className="faint">—</span>
                  )}
                </td>
                <td><SourceDots sources={row.sources} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {mapOpen ? <MappingModal onClose={() => setMapOpen(false)} /> : null}
    </div>
  );
}
