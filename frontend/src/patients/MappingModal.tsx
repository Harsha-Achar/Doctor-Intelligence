import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchMapping, fetchMappingLayer, fetchOverview } from './api';
import { Drawer, Icon, LAYER_META, Modal, fmt, layerTitle } from './widgets';

export function MappingModal({ onClose }: { onClose: () => void }) {
  const mapping = useQuery({ queryKey: ['pt-mapping'], queryFn: ({ signal }) => fetchMapping(signal) });
  const overview = useQuery({ queryKey: ['pt-overview'], queryFn: ({ signal }) => fetchOverview(signal) });
  const [layer, setLayer] = useState<string | null>(null);
  const records = useQuery({
    queryKey: ['pt-mapping-layer', layer],
    queryFn: ({ signal }) => fetchMappingLayer(layer || '', signal),
    enabled: Boolean(layer),
  });
  const navigate = useNavigate();
  const total = mapping.data?.records || 0;
  return (
    <>
      {!layer ? (
        <Modal title="How records were mapped to patients" onClose={onClose} tour="pt-map">
          {mapping.isLoading ? <p>Loading mapping…</p> : null}
          {mapping.isError ? <p>The mapping could not be loaded.</p> : null}
          {mapping.data ? (
            <>
              <p className="muted" style={{ margin: 0 }}>
                {fmt(total)} vendor records → {fmt(overview.data?.patients)} Daiichi patient IDs. Strongest evidence is used first; only uncertain records wait for a person.
              </p>
              <div className="stackbar" aria-hidden>
                {mapping.data.layers.map((item) =>
                  item.count ? (
                    <i key={item.layer} style={{ width: `${(item.count / (total || 1)) * 100}%`, background: LAYER_META[item.layer]?.color || 'var(--accent)' }} title={`${layerTitle(item.layer)}: ${item.count}`} />
                  ) : null,
                )}
              </div>
              <div className="mapgrid">
                {mapping.data.layers.map((item) => (
                  <button key={item.layer} className="mapcard" type="button" onClick={() => setLayer(item.layer)}>
                    <span className="dot" style={{ background: LAYER_META[item.layer]?.color || 'var(--neu)' }} />
                    <b>{item.pct}%</b>
                    <span className="t">{layerTitle(item.layer)}</span>
                    <span className="s">{item.description}</span>
                    <span className="ex">e.g. {LAYER_META[item.layer]?.example || item.example}</span>
                    <span className="n">{fmt(item.count)} records →</span>
                  </button>
                ))}
              </div>
              {mapping.data.quality_line ? (
                <div className="banner ok">
                  <Icon name="check" />
                  {mapping.data.quality_line}
                </div>
              ) : null}
            </>
          ) : null}
        </Modal>
      ) : null}
      {layer ? (
        <Drawer title={`${layerTitle(layer)} · ${fmt(records.data?.records.length)} records`} onClose={() => setLayer(null)} wide>
          {records.isLoading ? <p>Loading records…</p> : null}
          {records.data && records.data.records.length === 0 ? <p className="empty">No records in this layer.</p> : null}
          {records.data && records.data.records.length > 0 ? (
            <div className="tw card" style={{ boxShadow: 'none' }}>
              <table>
                <thead>
                  <tr>
                    <th>Record</th>
                    <th>Source</th>
                    <th>Evidence</th>
                    <th>Daiichi patient ID</th>
                  </tr>
                </thead>
                <tbody>
                  {records.data.records.slice(0, 80).map((row) => (
                    <tr
                      key={row.ref}
                      className={row.daiichi_patient_id ? 'click' : undefined}
                      onClick={() => {
                        if (!row.daiichi_patient_id) return;
                        onClose();
                        navigate(`/patients/${row.daiichi_patient_id}`);
                      }}
                    >
                      <td className="mono" style={{ whiteSpace: 'nowrap' }}>{row.ref}</td>
                      <td>{row.source_label}</td>
                      <td className="muted">{row.reason}</td>
                      <td className="mono">
                        {row.daiichi_patient_id || <span className="pill warn">Not yet mapped</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {records.data && records.data.records.length > 80 ? <p className="faint">Showing first 80.</p> : null}
        </Drawer>
      ) : null}
    </>
  );
}
