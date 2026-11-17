import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ErrorState } from '../components/ErrorState';
import { TableSkeleton } from '../components/Skeleton';
import {
  fetchFile,
  fetchOverview,
  fetchRun,
  fetchRuns,
  fetchSources,
  processUpload,
  reprocess,
  uploadPreview,
  type RunRow,
} from './api';
import { MappingModal } from './MappingModal';
import { Drawer, Icon, Modal, SRC, SourcePill, fmt, fmtStamp } from './widgets';

const STEP_DEFS = [
  { title: 'Read and validated files', test: /read/i, fallback: 'Required columns, data types and duplicate rows checked' },
  { title: 'Checked for identifiers', test: /identifier/i, fallback: 'No names, birth dates, addresses or phone numbers found' },
  { title: 'Built vendor patient profiles', test: /profile/i, fallback: 'Rows grouped by each vendor’s patient ID' },
  { title: 'Layer 1 · Program IDs', test: /layer 1/i, fallback: 'Linked across sources on hub case ID and copay card ID' },
  { title: 'Layer 2 · Vendor patient IDs', test: /layer 2/i, fallback: 'Records with a known vendor patient ID attached to their Daiichi patient' },
  { title: 'Layer 3 · Splink scoring', test: /layer 3|scoring/i, fallback: 'Remaining records scored on birth year, sex, ZIP3, prescriber, product, payer and dates' },
  { title: 'Layer 4 · AI evidence check', test: /layer 4/i, fallback: 'Low-confidence records explained with the 3 nearest patients' },
  { title: 'Issued Daiichi patient IDs', test: /issued/i, fallback: 'New IDs issued and records added to existing patients' },
  { title: 'Built journeys and AI summaries', test: /journey|summar/i, fallback: 'Timeline, doses, current status and summary refreshed' },
];

const SAMPLES: Record<string, { name: string; text: string }> = {
  hub: {
    name: 'hub_update_2026_10.csv',
    text: 'hub_patient_id,hub_case_id,copay_card_id,event,event_date,birth_year,sex,zip3,prescriber_npi,product,payer_type\nHP-91001,H-99101,,Enrolled,2026-10-02,1968,F,303,1576635514,Brand A,Commercial\n',
  },
  pharmacy: {
    name: 'sp_dispense_2026_10.csv',
    text: 'sp_patient_id,pharmacy_name,hub_case_id,copay_card_id,fill_date,ndc,quantity,days_supply,birth_year,sex,zip3,prescriber_npi,payer_type\nSPP-91001,Northstar Specialty,H-5001,,2026-10-03,0000-0001,3,21,1968,F,303,1576635514,Commercial\n',
  },
  claims: {
    name: 'claims_delivery_2026_10.csv',
    text: 'claims_patient_id,claim_id,claim_type,service_date,product_code,units,birth_year,sex,zip3,prescriber_npi,payer_type\nCV-91001,C880001,Medical,2026-10-04,J9415,3,1968,F,303,1576635514,Commercial\n',
  },
};

type Preview = Awaited<ReturnType<typeof uploadPreview>>;

export function DataPage() {
  const overview = useQuery({ queryKey: ['pt-overview'], queryFn: ({ signal }) => fetchOverview(signal) });
  const sources = useQuery({ queryKey: ['pt-sources'], queryFn: ({ signal }) => fetchSources(signal) });
  const runs = useQuery({ queryKey: ['pt-runs'], queryFn: ({ signal }) => fetchRuns(signal) });
  const [mapOpen, setMapOpen] = useState(false);
  const [fileId, setFileId] = useState<number | null>(null);
  const [historyId, setHistoryId] = useState<number | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [runId, setRunId] = useState<number | null>(null);
  const [source, setSource] = useState('claims');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [over, setOver] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const client = useQueryClient();

  function refresh() {
    void client.invalidateQueries({ queryKey: ['pt-overview'] });
    void client.invalidateQueries({ queryKey: ['pt-sources'] });
    void client.invalidateQueries({ queryKey: ['pt-runs'] });
    void client.invalidateQueries({ queryKey: ['pt-patients'] });
    void client.invalidateQueries({ queryKey: ['pt-review'] });
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    setUploadError('');
    try {
      setPreview(await uploadPreview(source, file));
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Upload failed.');
    }
  }

  async function onSample() {
    const sample = SAMPLES[source];
    const file = new File([sample.text], sample.name, { type: 'text/csv' });
    await onFile(file);
  }

  async function onProcess() {
    if (!preview || preview.rejected) return;
    const started = await processUpload(preview.upload_id);
    setPreview(null);
    setUploadOpen(false);
    setRunId(started.run_id);
  }

  async function onReprocess() {
    const started = await reprocess();
    setRunId(started.run_id);
  }

  const fileCount = overview.data?.files ?? sources.data?.sources.reduce((sum, card) => sum + card.files.length, 0) ?? 0;

  return (
    <div className="stack">
      {overview.isLoading ? <TableSkeleton rows={3} /> : null}
      {overview.isError ? <ErrorState message="Rows and patients could not be loaded." onRetry={() => overview.refetch()} /> : null}
      {overview.data ? (
        <div className="kpis k4" data-tour="pt-feeds">
          <div className="kpi">
            <span className="lbl">Rows processed</span>
            <span className="val">{fmt(overview.data.rows_processed)}</span>
            <span className="sub">{fileCount} files from 3 sources</span>
          </div>
          <Link className="kpi" to="/patients/list">
            <span className="lbl">Patients identified</span>
            <span className="val">{fmt(overview.data.patients)}</span>
            <span className="sub">One Daiichi patient ID each · view list →</span>
          </Link>
          <button className="kpi" type="button" data-tour="pt-map-open" onClick={() => setMapOpen(true)}>
            <span className="lbl">Mapped automatically</span>
            <span className="val">{overview.data.mapped_automatically_pct}%</span>
            <span className="sub">See how records were mapped →</span>
          </button>
          <Link className="kpi" to="/patients/review">
            <span className="lbl">Needs review</span>
            <span className="val" style={{ color: 'var(--warn)' }}>{overview.data.needs_review}</span>
            <span className="sub">Low confidence · pick from 3 nearest →</span>
          </Link>
        </div>
      ) : null}

      <div className="srcbar">
        <h2>Source files</h2>
        <span className="muted" style={{ fontSize: 13 }}>IDs and de-identified fields only</span>
        <div className="chips">
          <button className="btn" type="button" onClick={() => void onReprocess()}>
            <Icon name="reset" /> Reprocess all
          </button>
          <button className="btn primary" type="button" onClick={() => { setPreview(null); setUploadError(''); setUploadOpen(true); }}>
            <Icon name="upload" /> Upload CSV
          </button>
        </div>
      </div>

      {sources.isLoading ? <TableSkeleton rows={2} /> : null}
      {sources.isError ? <ErrorState message="Sources could not be loaded." onRetry={() => sources.refetch()} /> : null}
      <div className="srccards">
        {sources.data?.sources.map((card) => {
          const meta = SRC[card.source] || SRC.claims;
          return (
            <article key={card.source} className="card srccard" style={{ borderTop: `3px solid ${meta.color}` }}>
              <div className="card-b">
                <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                  <span className="ic" style={{ background: `${meta.color}1f`, color: meta.color }}>
                    <Icon name={meta.icon} />
                  </span>
                  <div>
                    <b style={{ fontSize: 15 }}>{card.label}</b>
                    <div className="muted" style={{ fontSize: 12.5 }}>{card.description}</div>
                  </div>
                </div>
                <div className="mini3">
                  <div><b>{fmt(card.rows)}</b><span>rows</span></div>
                  <div><b>{fmt(card.vendor_patients)}</b><span>vendor patients</span></div>
                  <div><b>{card.mapped_pct}%</b><span>mapped</span></div>
                </div>
                <div className="filelist">
                  {card.files.length === 0 ? <span className="faint">No files yet.</span> : null}
                  {card.files.map((file) => (
                    <button key={file.id} className="fileli" type="button" title={file.name} onClick={() => setFileId(file.id)}>
                      <Icon name="doc" size={14} />
                      <span className="mono">{file.name}</span>
                      {file.kind === 'uploaded' || file.kind === 'Uploaded' ? <span className="pill new">Uploaded</span> : <span className="faint">{file.period}</span>}
                    </button>
                  ))}
                </div>
              </div>
            </article>
          );
        })}
      </div>

      <div className="card">
        <div className="card-h">
          <h2>Processing history</h2>
          <span className="hint">Click a run for its steps</span>
        </div>
        <div className="card-b tw">
          {runs.isLoading ? <TableSkeleton /> : null}
          {runs.isError ? <ErrorState message="Processing history could not be loaded." onRetry={() => runs.refetch()} /> : null}
          {runs.data && runs.data.runs.length === 0 ? <p className="empty">No runs yet.</p> : null}
          {runs.data && runs.data.runs.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Started</th>
                  <th>Input</th>
                  <th className="n">Rows</th>
                  <th className="n">New patients</th>
                  <th className="n">Added to existing</th>
                  <th className="n">Needs review</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.runs.map((run) => (
                  <tr key={run.id} className="click" onClick={() => (run.status === 'running' ? setRunId(run.id) : setHistoryId(run.id))}>
                    <td className="mono" style={{ whiteSpace: 'nowrap' }}>RUN-{run.id}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>{fmtStamp(run.started_at)}</td>
                    <td>{run.input}</td>
                    <td className="n">{fmt(run.rows)}</td>
                    <td className="n">{fmt(run.new_patients)}</td>
                    <td className="n">{fmt(run.added_to_existing)}</td>
                    <td className="n">{run.review_count}</td>
                    <td>
                      <span className={`pill ${run.status === 'failed' ? 'bad' : run.status === 'running' ? 'acc' : 'ok'}`}>
                        {run.status === 'completed' ? 'Completed' : run.status === 'running' ? 'Running' : 'Failed'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </div>
      </div>

      {mapOpen ? <MappingModal onClose={() => setMapOpen(false)} /> : null}
      {fileId != null ? <FileDrawer id={fileId} onClose={() => setFileId(null)} /> : null}
      {historyId != null ? <RunDrawer id={historyId} onClose={() => setHistoryId(null)} /> : null}
      {uploadOpen ? (
        <UploadModal
          source={source}
          preview={preview}
          over={over}
          error={uploadError}
          onSource={(value) => { setSource(value); setPreview(null); }}
          onFile={(file) => void onFile(file)}
          onSample={() => void onSample()}
          onProcess={() => void onProcess()}
          onDrag={setOver}
          onClose={() => { setUploadOpen(false); setPreview(null); }}
          onReset={() => setPreview(null)}
        />
      ) : null}
      {runId != null ? (
        <ProgressModal
          id={runId}
          onClose={() => {
            setRunId(null);
            refresh();
          }}
        />
      ) : null}
    </div>
  );
}

function UploadModal({
  source,
  preview,
  over,
  error,
  onSource,
  onFile,
  onSample,
  onProcess,
  onDrag,
  onClose,
  onReset,
}: {
  source: string;
  preview: Preview | null;
  over: boolean;
  error: string;
  onSource: (value: string) => void;
  onFile: (file: File | undefined) => void;
  onSample: () => void;
  onProcess: () => void;
  onDrag: (value: boolean) => void;
  onClose: () => void;
  onReset: () => void;
}) {
  const rows = (preview?.mapping || []).filter((row) => !(row.field === 'hub' && source === 'claims'));
  return (
    <Modal title="Upload patient data (CSV)" onClose={onClose}>
      {!preview ? (
        <>
          <div className="muted" style={{ fontSize: 13 }}>1 · Which source is this file from?</div>
          <div className="modes">
            {(['hub', 'pharmacy', 'claims'] as const).map((item) => (
              <button key={item} className={`mode${source === item ? ' on' : ''}`} type="button" onClick={() => onSource(item)}>
                <b>{SRC[item].label}</b>
                <span>{{ hub: 'Enrollments and access steps', pharmacy: 'Dispenses and status', claims: 'Pharmacy and medical claims' }[item]}</span>
              </button>
            ))}
          </div>
          <div className="muted" style={{ fontSize: 13 }}>2 · Add the file</div>
          <label className={`drop${over ? ' over' : ''}`} onDragOver={(event) => { event.preventDefault(); onDrag(true); }} onDragLeave={() => onDrag(false)} onDrop={(event) => { event.preventDefault(); onDrag(false); onFile(event.dataTransfer.files[0]); }}>
            <Icon name="upload" size={30} />
            <b>Drop a CSV here or browse</b>
            <span className="muted">IDs and de-identified fields only. Files with names, birth dates or addresses are rejected.</span>
            <input type="file" accept=".csv,text/csv" hidden onChange={(event) => { onFile(event.target.files?.[0]); event.target.value = ''; }} />
          </label>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="muted">No file handy?</span>
            <button className="btn" type="button" onClick={onSample}>
              <Icon name="doc" /> Use sample {SRC[source].label.toLowerCase()} file
            </button>
          </div>
          {error ? <ErrorState message={error} /> : null}
        </>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="pill acc">{preview.filename || 'File'}</span>
            <SourcePill source={source} />
            <span className="muted">{fmt(preview.rows)} rows · {preview.mapping.length} fields</span>
          </div>
          {preview.rejected || !preview.identifier_ok ? (
            <div className="banner bad"><Icon name="alert" />{preview.reject_reason || preview.identifier_message}</div>
          ) : (
            <div className="banner ok"><Icon name="shield" />Identifier check passed: no names, birth dates, addresses or phone numbers.</div>
          )}
          <div className="tw card" style={{ boxShadow: 'none' }}>
            <table>
              <thead>
                <tr>
                  <th>Standard field</th>
                  <th>Column in your file</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.field}>
                    <td>
                      {row.label}
                      {row.required ? null : <span className="faint"> (optional)</span>}
                    </td>
                    <td className="mono">{row.column || '—'}</td>
                    <td>
                      <span className={`pill ${row.state === 'Mapped' ? 'ok' : row.state === 'Missing' ? 'bad' : 'neu'}`}>{row.state}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {preview.rows_held_back ? <p className="muted">{fmt(preview.rows)} rows ready · {fmt(preview.rows_held_back)} held back</p> : null}
          {preview.preview_rows.length ? (
            <details className="how">
              <summary>Preview first 5 rows</summary>
              <div className="tw">
                <table>
                  <thead>
                    <tr>
                      {Object.keys(preview.preview_rows[0]).map((key) => (
                        <th key={key} className="mono" style={{ fontSize: 11.5 }}>{key}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.preview_rows.slice(0, 5).map((row, index) => (
                      <tr key={index}>
                        {Object.values(row).map((value, cell) => (
                          <td key={cell} className="mono" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{value}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          ) : null}
          <div className="modal-f" style={{ padding: 0, border: 0 }}>
            <button className="btn" type="button" onClick={onReset}>Choose another file</button>
            <button className="btn primary" type="button" disabled={preview.rejected || !preview.identifier_ok} onClick={onProcess}>Process file</button>
          </div>
        </>
      )}
    </Modal>
  );
}

function alignSteps(run: RunRow | undefined) {
  const logged = run?.steps || [];
  return STEP_DEFS.map((step) => {
    const found = logged.find((item) => step.test.test(item.title));
    return { title: step.title, detail: found?.detail || step.fallback, at: found?.at, ready: Boolean(found) || run?.status === 'completed' || run?.status === 'failed' };
  });
}

function ProgressModal({ id, onClose }: { id: number; onClose: () => void }) {
  const run = useQuery({
    queryKey: ['pt-run', id],
    queryFn: ({ signal }) => fetchRun(id, signal),
    refetchInterval: (query) => (query.state.data && query.state.data.status !== 'running' ? false : 700),
  });
  const steps = useMemo(() => alignSteps(run.data), [run.data]);
  const ready = run.data?.status === 'running' ? steps.filter((step) => step.ready).length : run.data ? steps.length : 0;
  const [shown, setShown] = useState(0);
  useEffect(() => {
    if (shown >= ready) return;
    const timer = window.setTimeout(() => setShown((value) => value + 1), 420);
    return () => window.clearTimeout(timer);
  }, [shown, ready]);
  const done = run.data && run.data.status !== 'running' && shown >= steps.length;
  const percent = done ? 100 : Math.round((shown / steps.length) * 100);
  const data = run.data;
  const upload = /upload/i.test(data?.input || '');
  const ids = (data?.result?.updated_patient_ids || []).slice(0, 8);
  return (
    <Modal
      title={upload ? `Processing ${data?.input.replace(/^Upload\s*/, '') || 'file'}` : `Reprocessing all files · RUN-${id}`}
      extra={<span className="pill acc">{done ? 'Done' : `${percent}%`}</span>}
      onClose={done ? onClose : undefined}
      footer={done ? <button className="btn primary" type="button" onClick={onClose}>Close</button> : null}
    >
      <div className="pbar"><i style={{ width: `${percent}%` }} /></div>
      <div className="stages">
        {steps.map((step, index) => {
          const state = index < shown ? 'done' : index === shown && !done ? 'run' : '';
          return (
            <div key={step.title} className={`stg ${state}`}>
              <div className="st">{index < shown ? <Icon name="check" size={12} /> : null}</div>
              <div>
                <b>{step.title}</b>
                {index < shown ? <small>{step.detail}</small> : null}
              </div>
              <div />
            </div>
          );
        })}
      </div>
      <div className="log" aria-live="polite">
        {steps.slice(0, shown).map((step) => (
          <div key={step.title}>
            <span className="t">{step.at ? fmtStamp(step.at).slice(-5) : new Date().toTimeString().slice(0, 8)}</span>
            {step.detail}
          </div>
        ))}
      </div>
      {done && data ? (
        <div style={{ display: 'grid', gap: 10 }}>
          <div className="result">
            {upload ? (
              <>
                <Link to="/patients/list" onClick={onClose}><b>{fmt(data.new_patients)}</b><span>New Daiichi IDs</span></Link>
                <Link to="/patients/list" onClick={onClose}><b>{fmt(data.added_to_existing)}</b><span>Added to existing</span></Link>
                <Link to="/patients/review" onClick={onClose}><b>{fmt(data.review_count)}</b><span>Low confidence</span></Link>
              </>
            ) : (
              <>
                <Link to="/patients/list" onClick={onClose}><b>{fmt(data.result?.patients ?? data.new_patients)}</b><span>Daiichi patient IDs</span></Link>
                <Link to="/patients/review" onClick={onClose}><b>{fmt(data.review_count)}</b><span>Low confidence</span></Link>
              </>
            )}
          </div>
          {ids.length ? (
            <div className="chips">
              <span className="muted" style={{ fontSize: 12.5 }}>Updated patients:</span>
              {ids.map((patientId) => (
                <Link key={patientId} className="cite" to={`/patients/${patientId}`} onClick={onClose}>{patientId}</Link>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      {run.isError ? <ErrorState message="This run could not be read." onRetry={() => run.refetch()} /> : null}
    </Modal>
  );
}

function RunDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const run = useQuery({ queryKey: ['pt-run', id], queryFn: ({ signal }) => fetchRun(id, signal) });
  const steps = alignSteps(run.data);
  return (
    <Drawer title={`RUN-${id} · ${run.data?.input || 'Run'}`} onClose={onClose}>
      {run.isLoading ? <p>Loading run…</p> : null}
      {run.isError ? <ErrorState message="This run could not be opened." onRetry={() => run.refetch()} /> : null}
      <div className="stages">
        {steps.map((step) => (
          <div key={step.title} className="stg done">
            <div className="st"><Icon name="check" size={12} /></div>
            <div>
              <b>{step.title}</b>
              <small>{step.detail}</small>
            </div>
            <div />
          </div>
        ))}
      </div>
      {run.data ? <p className="muted" style={{ margin: 0 }}>Started {fmtStamp(run.data.started_at)}{run.data.duration ? ` · ${Math.round(run.data.duration)} seconds` : ''}</p> : null}
    </Drawer>
  );
}

function FileDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const file = useQuery({ queryKey: ['pt-file', id], queryFn: ({ signal }) => fetchFile(id, signal) });
  const columns = file.data?.columns || [];
  const data = file.data;
  return (
    <Drawer title={data?.name || 'File'} onClose={onClose} wide>
      {file.isLoading ? <p>Loading file…</p> : null}
      {file.isError ? <ErrorState message="This file could not be opened." onRetry={() => file.refetch()} /> : null}
      {data ? (
        <>
          <div className="chips">
            {data.source ? <SourcePill source={data.source} /> : null}
            <span className={`pill ${data.kind === 'uploaded' ? 'new' : 'neu'}`}>{data.kind === 'uploaded' ? 'Uploaded' : 'Historical'}</span>
            <span className="muted">{fmt(data.row_count)} rows · {fmt(data.vendor_patients)} vendor patient IDs{data.period ? ` · ${data.period}` : ''}</span>
          </div>
          <div>
            <h3 className="subh">Columns</h3>
            <div className="chips">{columns.map((column) => <span key={column} className="tok">{column}</span>)}</div>
          </div>
          <div>
            <h3 className="subh">Sample rows</h3>
            {data.rows.length === 0 ? <p className="empty">This file has no stored rows.</p> : null}
            {data.rows.length > 0 ? (
              <div className="tw card" style={{ boxShadow: 'none' }}>
                <table>
                  <thead>
                    <tr>{columns.map((column) => <th key={column} className="mono" style={{ fontSize: 11 }}>{column}</th>)}</tr>
                  </thead>
                  <tbody>
                    {data.rows.slice(0, 8).map((row, index) => (
                      <tr key={index}>
                        {columns.map((column) => (
                          <td key={column} className="mono" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{row.values[column]}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
          {data.rows_held_back ? <p className="muted">{data.rows_held_back} rows were held back and were not used for matching.</p> : null}
          <p className="muted" style={{ margin: 0 }}>Each vendor patient ID only works inside this source. Program IDs and scoring link it to the other sources.</p>
        </>
      ) : null}
    </Drawer>
  );
}
