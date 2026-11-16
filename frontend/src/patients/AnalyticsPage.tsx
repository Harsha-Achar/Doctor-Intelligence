import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ErrorState } from '../components/ErrorState';
import { TableSkeleton } from '../components/Skeleton';
import { fetchAnalytics, type Analytics } from './api';
import { SRC, fmt, num, statusClass } from './widgets';

const LAYER_LABEL: Record<string, string> = {
  program_id: 'Program ID',
  vendor_id: 'Source patient ID',
  score: 'Splink score',
  reviewer: 'Reviewer',
  first_record: 'First record',
  needs_review: 'Needs review',
};

export function AnalyticsPage() {
  const [brand, setBrand] = useState('all');
  const [payer, setPayer] = useState('all');
  const [status, setStatus] = useState('all');
  const [focus, setFocus] = useState('all');
  const [shown, setShown] = useState(20);
  const data = useQuery({
    queryKey: ['pt-analytics', brand, payer],
    queryFn: ({ signal }) => fetchAnalytics(brand, payer, signal),
  });
  const body = data.data;
  return (
    <div data-tour="pt-analytics">
      {data.isLoading ? <TableSkeleton rows={4} /> : null}
      {data.isError ? <ErrorState message="Journey analytics could not be loaded." onRetry={() => data.refetch()} /> : null}
      {body?.banner ? <p className="banner warn">{body.banner}</p> : null}
      <div className="card">
        <div className="card-b filterbar">
          <span className="muted">Brand</span>
          <div className="chips">
            {[['all', 'All'], ['Brand A', 'Brand A'], ['Brand B', 'Brand B'], ['Brand C', 'Brand C']].map(([value, label]) => (
              <button key={value} className={`chip${brand === value ? ' on' : ''}`} type="button" onClick={() => { setBrand(value); setShown(20); }}>{label}</button>
            ))}
          </div>
          <span className="muted">Payer</span>
          <div className="chips">
            {['all', 'Commercial', 'Medicare', 'Medicaid'].map((value) => (
              <button key={value} className={`chip${payer === value ? ' on' : ''}`} type="button" onClick={() => { setPayer(value); setShown(20); }}>{value === 'all' ? 'All' : value}</button>
            ))}
          </div>
          <span className="faint" style={{ marginLeft: 'auto', fontSize: 12.5 }}>{brand === 'all' ? 'Brands are fictional placeholders' : body?.survival.find((item) => item.brand === brand)?.description}</span>
        </div>
      </div>
      {body ? <AnalyticsBody data={body} status={status} focus={focus} shown={shown} onStatus={setStatus} onPayer={(value) => { setPayer(value); setShown(20); }} onFocus={(value) => { setFocus(value); setShown(20); }} onMore={() => setShown((value) => value + 20)} /> : null}
    </div>
  );
}

function AnalyticsBody({
  data,
  status,
  focus,
  shown,
  onStatus,
  onPayer,
  onFocus,
  onMore,
}: {
  data: Analytics;
  status: string;
  focus: string;
  shown: number;
  onStatus: (value: string) => void;
  onPayer: (value: string) => void;
  onFocus: (value: string) => void;
  onMore: () => void;
}) {
  const kpis = data.kpis;
  const funnelMax = Math.max(1, ...data.funnel.map((step) => num(step.count)));
  const neverMax = Math.max(1, ...data.never_reasons.map((row) => num(row.count)));
  const timeMax = Math.max(1, ...data.time_steps.map((step) => step.days || 0));
  const payerMax = Math.max(1, ...data.days_by_payer.map((row) => row.days || 0));
  const stopMax = Math.max(1, ...data.stops.map((row) => num(row.count)));
  const delayMax = Math.max(1, ...data.delay_causes.map((row) => num(row.count)));
  const rows = data.journeys.filter((row) => {
    if (status !== 'all' && row.status !== status) return false;
    if (focus === 'multi' && row.sources.length < 2) return false;
    if (focus === 'never' && row.status !== 'Never started') return false;
    if (focus === 'delay' && !row.delayed) return false;
    if (focus === 'nohub' && (row.in_hub || (row.status !== 'On therapy' && row.status !== 'Stopped'))) return false;
    if (focus.startsWith('reason:') && (row.status !== 'Never started' || row.stop_reason !== focus.slice(7))) return false;
    if (focus.startsWith('stop:') && row.stop_reason !== focus.slice(5)) return false;
    if (focus === 'hub' && !row.in_hub) return false;
    return true;
  });
  return (
    <>
      <div className="kpis k6">
        <button className="kpi" type="button" onClick={() => onFocus('multi')}>
          <span className="lbl">Patients with a linked journey</span>
          <span className="val">{fmt(kpis.linked_journeys)}</span>
          <span className="sub">of {fmt(kpis.patients)} patients · seen in 2 or more sources</span>
        </button>
        <div className="kpi">
          <span className="lbl">Median days to first dose</span>
          <span className="val">{kpis.median_days_to_first_dose ?? '—'} <small>days</small></span>
          <span className="sub">From hub enrollment to first infusion or fill</span>
        </div>
        <button className="kpi" type="button" onClick={() => onFocus('never')}>
          <span className="lbl">Never started therapy</span>
          <span className="val">{kpis.never_started_pct}%</span>
          <span className="sub">{fmt(kpis.never_started)} of {fmt(kpis.hub_patients)} hub patients · see reasons below</span>
        </button>
        <div className="kpi">
          <span className="lbl">On therapy at 6 months</span>
          <span className="val">{kpis.on_therapy_6_months_pct}%</span>
          <span className="sub">Among patients who started at least 6 months ago</span>
        </div>
        <button className="kpi" type="button" onClick={() => onFocus('delay')}>
          <span className="lbl">Patients with a dose delay</span>
          <span className="val">{kpis.dose_delay_pct}%</span>
          <span className="sub">Delay of more than 7 days between doses</span>
        </button>
        <button className="kpi" type="button" onClick={() => onFocus('nohub')}>
          <span className="lbl">Treated outside the hub</span>
          <span className="val">{kpis.outside_hub_pct}%</span>
          <span className="sub">Seen only in pharmacy and claims · a support opportunity</span>
        </button>
      </div>
      <div className="card">
        <div className="card-h">
          <h2>Patient journey: from hub enrollment to 6 months on therapy</h2>
          <span className="hint">Only possible by linking hub, pharmacy and claims · click a step</span>
        </div>
        <div className="card-b">
          <div className="funnel">
            {data.funnel.map((step, index) => {
              const count = num(step.count);
              const previous = index ? num(data.funnel[index - 1].count) : count;
              const base = index === data.funnel.length - 1 && step.denominator != null ? num(step.denominator) : funnelMax;
              const width = base ? (count / base) * 100 : 0;
              return (
                <button key={step.label} className="fstep" type="button" onClick={() => onFocus(index === 0 ? 'hub' : 'all')}>
                  <span className="fl">
                    <b>{step.label}</b>
                    <span className="muted">{index === 0 ? 'Starting point' : index === data.funnel.length - 1 ? `of ${fmt(step.denominator)} who started 6+ months ago` : `${fmt(Math.max(0, previous - count))} lost`}</span>
                  </span>
                  <span className="ft"><i style={{ width: `${width}%`, background: index === data.funnel.length - 1 ? 'var(--ok)' : 'var(--accent)' }} /></span>
                  <span className="num"><b>{fmt(step.count)}</b> {index ? <span className="muted">{base ? `${Math.round((count / base) * 100)}%` : ''}</span> : null}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
      <div className="grid g2">
        <div className="card">
          <div className="card-h"><h2>Why patients never started</h2><span className="hint">Reasons from the hub, confirmed by no dispense or claim</span></div>
          <div className="card-b bars">
            {data.never_reasons.length === 0 ? <p className="muted">No patients in this group.</p> : null}
            {data.never_reasons.map((row) => (
              <button key={row.label} className="bar-row" type="button" onClick={() => onFocus(`reason:${row.label}`)}>
                <span>{row.label}</span>
                <div className="b alt" style={{ width: `${(num(row.count) / neverMax) * 100}%` }} />
                <span className="num">{fmt(row.count)}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="card">
          <div className="card-h"><h2>Where time is spent before the first dose</h2><span className="hint">Median days per step</span></div>
          <div className="card-b bars">
            {data.time_steps.map((step) => (
              <div className="bar-row" key={step.label}>
                <span>{step.label}</span>
                <div className="b" style={{ width: `${((step.days || 0) / timeMax) * 100}%` }} />
                <span className="num">{step.days != null ? `${step.days}d` : '—'}</span>
              </div>
            ))}
            <h3 className="subh" style={{ marginTop: 10 }}>Median days to first dose by payer</h3>
            {data.days_by_payer.map((row) => (
              <button key={row.payer} className="bar-row" type="button" onClick={() => onPayer(row.payer)}>
                <span>{row.payer} <span className="faint">({fmt(row.patients)})</span></span>
                <div className="b" style={{ width: `${((row.days || 0) / payerMax) * 100}%`, background: row.payer === 'Medicaid' ? 'var(--bad)' : row.payer === 'Medicare' ? 'var(--warn)' : 'var(--ok)' }} />
                <span className="num">{row.days != null ? `${row.days}d` : '—'}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="grid g2">
        <div className="card">
          <div className="card-h"><h2>How long patients stay on therapy</h2><span className="hint">Share still on therapy, by month since first dose</span></div>
          <div className="card-b hist"><Survival curves={data.survival} /></div>
        </div>
        <div className="card">
          <div className="card-h"><h2>Why patients stopped</h2><span className="hint">From claims and pharmacy, explained by hub notes</span></div>
          <div className="card-b bars">
            {data.stops.map((row) => (
              <button key={row.label} className="bar-row" type="button" onClick={() => onFocus(`stop:${row.label}`)}>
                <span>{row.label}</span>
                <div className="b" style={{ width: `${(num(row.count) / stopMax) * 100}%`, background: 'var(--neu)' }} />
                <span className="num">{fmt(row.count)}</span>
              </button>
            ))}
            <h3 className="subh" style={{ marginTop: 10 }}>Dose delays by cause</h3>
            {data.delay_causes.length === 0 ? <p className="muted">No delayed doses in this cohort.</p> : null}
            {data.delay_causes.map((row) => (
              <div className="bar-row" key={row.label}>
                <span>{row.label}</span>
                <div className="b alt" style={{ width: `${(num(row.count) / delayMax) * 100}%` }} />
                <span className="num">{fmt(row.count)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="grid g2">
        <div className="card">
          <div className="card-h"><h2>Prescribers</h2><span className="hint">Linked to golden doctor records · counts under 11 hidden</span></div>
          <div className="card-b tw">
            <table>
              <thead><tr><th>Doctor</th><th className="n">Patients</th><th className="n">Days to 1st dose</th><th className="n">Side-effect stops</th></tr></thead>
              <tbody>
                {data.prescribers.map((row) => (
                  <tr key={row.name} className={row.doctor_id ? 'click' : undefined}>
                    <td>{row.doctor_id ? <Link className="link" to={`/doctors/${row.doctor_id}`}><b>{row.name}</b></Link> : <b>{row.name}</b>}</td>
                    <td className="n">{fmt(row.patients)}</td>
                    <td className="n">{row.median_days ?? '—'}</td>
                    <td className="n">{fmt(row.side_effect_stops)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="card">
          <div className="card-h"><h2>Patients by state</h2><span className="hint">Counts under 11 hidden</span></div>
          <div className="card-b tw">
            <table>
              <thead><tr><th>State</th><th className="n">Patients</th><th className="n">Treated outside hub</th></tr></thead>
              <tbody>
                {data.states.map((row) => (
                  <tr key={row.state}><td>{row.state}</td><td className="n">{fmt(row.patients)}</td><td className="n">{fmt(row.outside_hub)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <div className="card">
        <div className="card-h"><h2>What linking adds</h2></div>
        <div className="card-b">
          <div className="impact">
            <div className="tile"><span className="k" style={{ color: 'var(--neu)' }}>Hub data alone</span><b>Access steps</b><p>Shows enrollment, insurance checks and approvals, but not whether the patient stayed on therapy.</p></div>
            <div className="tile"><span className="k" style={{ color: 'var(--neu)' }}>Claims and pharmacy alone</span><b>Treatment</b><p>Show doses and stops, but not why a patient never started or what caused a delay.</p></div>
            <div className="tile"><span className="k" style={{ color: 'var(--ok)' }}>Linked to one Daiichi patient ID</span><b>{fmt(kpis.linked_journeys)} full journeys</b><p>Time to therapy, reasons for not starting, persistence and delays for the same anonymous patient, without anyone seeing who they are.</p></div>
          </div>
        </div>
      </div>
      <div className="card">
        <div className="card-h">
          <h2>Patient journeys</h2>
          <span className="hint">Anonymous IDs only · click a patient to see the timeline</span>
          <div className="chips right">
            {['all', 'On therapy', 'Stopped', 'Never started'].map((value) => (
              <button key={value} className={`chip${status === value ? ' on' : ''}`} type="button" onClick={() => onStatus(value)}>{value === 'all' ? 'All' : value}</button>
            ))}
          </div>
        </div>
        <div className="card-b tw">
          <table>
            <thead>
              <tr><th>Patient</th><th>Brand</th><th>Payer</th><th>Sources</th><th>Linked by</th><th>Status</th><th>Prescriber</th></tr>
            </thead>
            <tbody>
              {rows.slice(0, shown).map((row) => (
                <tr key={row.id} className="click">
                  <td className="mono"><Link className="link" to={`/patients/${row.id}`}>{row.id}</Link></td>
                  <td>{row.brand}</td>
                  <td>{row.payer}</td>
                  <td>{row.sources.map((source) => <span key={source} className="pill" style={{ background: `${SRC[source]?.color || '#888'}22`, color: SRC[source]?.color, marginRight: 4 }}>{SRC[source]?.label || source}</span>)}</td>
                  <td className="muted">{row.linked_by.split(', ').map((item) => LAYER_LABEL[item] || item).join(', ')}</td>
                  <td><span className={`pill ${statusClass(row.status)}`}>{row.status}</span></td>
                  <td>{row.doctor_id ? <Link className="link" to={`/doctors/${row.doctor_id}`}>{row.prescriber}</Link> : row.prescriber}</td>
                </tr>
              ))}
              {rows.length > shown ? (
                <tr><td colSpan={7}><button className="link" type="button" onClick={onMore}>Show more ({rows.length - shown} more)</button></td></tr>
              ) : null}
              {rows.length === 0 ? <tr><td colSpan={7} className="muted">No patients match.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function Survival({ curves }: { curves: Analytics['survival'] }) {
  const W = 560;
  const H = 230;
  const pad = 34;
  const xm = 365;
  const X = (day: number) => pad + (day / xm) * (W - pad * 1.6);
  const Y = (share: number) => H - pad + 6 - share * (H - pad * 1.6);
  const colors = ['var(--accent)', 'var(--ok)', 'var(--warn)'];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Share of patients still on therapy by month">
      {[0, 0.25, 0.5, 0.75, 1].map((share) => (
        <g key={share}>
          <line x1={pad} x2={W - pad * 0.6} y1={Y(share)} y2={Y(share)} stroke="var(--line)" />
          <text x={pad - 6} y={Y(share) + 4} textAnchor="end">{share * 100}%</text>
        </g>
      ))}
      {[0, 3, 6, 9, 12].map((month) => (
        <text key={month} x={X(month * 30.4)} y={H - 8} textAnchor="middle">{month} mo</text>
      ))}
      {curves.map((curve, index) => {
        let d = `M${X(0)} ${Y(1)}`;
        curve.points.filter((point) => point[0] <= xm).forEach(([day, share]) => {
          d += ` H${X(day)} V${Y(share)}`;
        });
        d += ` H${X(xm)}`;
        const at = [...curve.points].reverse().find((point) => point[0] <= 182)?.[1] ?? curve.at_6_months;
        return (
          <g key={curve.brand}>
            <path d={d} fill="none" stroke={colors[index] || 'var(--accent)'} strokeWidth="2.4" />
            <text x={X(xm) - 4} y={Y(at) - 6} textAnchor="end" style={{ fill: colors[index], fontWeight: 600 }}>{curve.brand} · {Math.round(curve.at_6_months * 100)}% at 6 mo</text>
          </g>
        );
      })}
    </svg>
  );
}
