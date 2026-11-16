import { useQuery } from '@tanstack/react-query';
import { ErrorState } from '../components/ErrorState';
import { TableSkeleton } from '../components/Skeleton';
import { fetchPrivacy } from './api';
import { Icon, fmtStamp } from './widgets';

const RECEIVED: Record<string, string> = {
  identities: 'Identities',
  vendor_patient_ids: 'Vendor patient IDs',
  program_ids: 'Program IDs',
  fields: 'Generalized fields',
  daiichi_patient_id: 'Daiichi patient ID',
};

export function PrivacyPage() {
  const privacy = useQuery({ queryKey: ['pt-privacy'], queryFn: ({ signal }) => fetchPrivacy(signal) });
  if (privacy.isLoading) return <TableSkeleton rows={4} />;
  if (privacy.isError) return <ErrorState message="Privacy and audit could not be loaded." onRetry={() => privacy.refetch()} />;
  if (!privacy.data) return <p className="empty">Nothing recorded yet.</p>;
  const data = privacy.data;
  return (
    <div>
      {data.small_cell_min === 0 ? <p className="banner warn">Small-cell rule off for synthetic demo data</p> : null}
      <div className="grid g2">
        <div className="card">
          <div className="card-h"><h2>What arrives from vendors</h2></div>
          <div className="card-b">
            <dl className="kv">
              {Object.entries(data.received).map(([key, value]) => (
                <span key={key} style={{ display: 'contents' }}>
                  <dt>{RECEIVED[key] || key}</dt>
                  <dd>{value}</dd>
                </span>
              ))}
              <dt>Data agreements</dt>
              <dd className="mono">Hub v4 · Pharmacy aggregator v2 · Claims vendor v3</dd>
            </dl>
          </div>
        </div>
        <div className="card">
          <div className="card-h"><h2>Matching layers and thresholds</h2></div>
          <div className="card-b tw">
            <table>
              <thead><tr><th>Layer</th><th>Evidence</th><th>Rule</th></tr></thead>
              <tbody>
                {data.layers.map((row) => (
                  <tr key={row.layer}>
                    <td><b>{row.layer}</b></td>
                    <td>{row.evidence}</td>
                    <td>{row.rule}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <div className="card">
        <div className="card-h"><h2>Who can see what</h2></div>
        <div className="card-b tw">
          <table>
            <thead>
              <tr>
                <th>Role</th>
                <th>Vendor patient IDs</th>
                <th>Assign low-confidence records</th>
                <th>Patient-level journeys</th>
                <th>Aggregate dashboards</th>
              </tr>
            </thead>
            <tbody>
              {data.roles.map((row) => (
                <tr key={row.role}>
                  <td><b>{row.role}</b></td>
                  {[row.vendor_ids, row.assign, row.journeys, row.dashboards].map((value, index) => (
                    <td key={index}><span className={`pill ${value.startsWith('No') ? 'neu' : 'ok'}`}>{value}</span></td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="grid g2">
        <div className="card">
          <div className="card-h"><h2>Privacy checks · last run</h2></div>
          <div className="card-b">
            <div className="list">
              {data.checks.map((check) => (
                <div className="li" key={check.title}>
                  <div className="ic ok"><Icon name="check" /></div>
                  <div className="tx"><b>{check.title}</b><span>{check.detail}</span></div>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="card">
          <div className="card-h"><h2>Audit log</h2></div>
          <div className="card-b">
            {data.audit.length === 0 ? <p className="empty">No audit entries yet.</p> : null}
            <div className="list">
              {data.audit.map((row, index) => (
                <div className="li" key={index}>
                  <div className="ic acc"><Icon name="review" /></div>
                  <div className="tx">
                    <b>{auditText(row.action, row.details)}</b>
                    <span className="mono">{fmtStamp(row.at)} · {row.actor}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function auditText(action: string, details: Record<string, unknown>) {
  if (action === 'pipeline') return `Processing run ${details.run_id ?? ''} · ${details.patients ?? ''} patients`;
  if (action === 'review_assign') return `Assigned a record to ${details.daiichi_patient_id || 'a Daiichi patient'}`;
  if (action === 'review_new') return 'Created a new Daiichi patient ID from a low-confidence record';
  if (action === 'review_defer') return 'Deferred a low-confidence record';
  if (action === 'review_undo') return 'Undid a review decision';
  return action.replaceAll('_', ' ');
}
