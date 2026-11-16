import { useEffect, useRef, type ReactNode } from 'react';

const PATHS: Record<string, ReactNode> = {
  users: (
    <>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14c2 .7 3.5 2.9 3.5 6" />
    </>
  ),
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  upload: <path d="M12 15V4M7 8.5 12 4l5 4.5M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />,
  reset: <path d="M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5" />,
  x: <path d="M6 6l12 12M18 6 6 18" />,
  alert: <path d="M12 3 2 20h20L12 3ZM12 10v4M12 17h.01" />,
  move: (
    <>
      <path d="M12 21s-7-5.5-7-11a7 7 0 0 1 14 0c0 5.5-7 11-7 11Z" />
      <circle cx="12" cy="10" r="2.5" />
    </>
  ),
  doc: (
    <>
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
      <path d="M14 3v6h6" />
    </>
  ),
  dollar: <path d="M12 2v20M17 6.5C16 5 14.3 4.5 12 4.5c-2.8 0-4.5 1.3-4.5 3.3 0 4.5 9.5 2.3 9.5 7 0 2.1-1.9 3.6-5 3.6-2.4 0-4.2-.7-5.2-2.2" />,
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </>
  ),
  back: <path d="m15 18-6-6 6-6" />,
  spark: <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6" />,
  shield: <path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z" />,
  review: (
    <>
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M8 8h8M8 12h8M8 16h5" />
    </>
  ),
};

export function Icon({ name, size = 16 }: { name: keyof typeof PATHS; size?: number }) {
  const filled = name === 'check' ? '2.4' : '2';
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth={filled} aria-hidden>
      {PATHS[name]}
    </svg>
  );
}

export function fmt(value: number | string | null | undefined) {
  if (value == null || value === '') return '—';
  if (typeof value === 'number') return value.toLocaleString('en-US');
  return String(value);
}

export function num(value: number | string | null | undefined) {
  return typeof value === 'number' ? value : 0;
}

export function sgn(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return '—';
  const rounded = Math.round(value);
  return rounded > 0 ? `+${rounded}` : String(rounded);
}

export function fmtStamp(value: string | null | undefined) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.replace('T', ' ').slice(0, 16);
  const day = date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  const time = date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' });
  return `${day} ${time}`;
}

export function shortDate(label: string | null | undefined) {
  if (!label) return '—';
  return label.replace(/\s+\d{4}$/, '');
}

export const SRC: Record<string, { label: string; color: string; icon: keyof typeof PATHS }> = {
  hub: { label: 'Hub', color: '#5b45c2', icon: 'users' },
  pharmacy: { label: 'Specialty pharmacy', color: '#0d8065', icon: 'doc' },
  claims: { label: 'Claims', color: '#1e5aa8', icon: 'dollar' },
};

export const LAYER_META: Record<string, { name: string; short: string; color: string; example: string }> = {
  program_id: {
    name: 'Program ID',
    short: 'Layer 1',
    color: 'var(--ok)',
    example: 'A pharmacy referral carries the same hub case ID as the hub enrollment',
  },
  vendor_id: {
    name: 'Source patient ID',
    short: 'Layer 2',
    color: '#35a98c',
    example: "Two claims for the same claims-vendor patient ID",
  },
  score: {
    name: 'Splink score',
    short: 'Layer 3',
    color: 'var(--accent)',
    example: 'A claim 2 days after a pharmacy fill, same prescriber, birth year, ZIP3 and product',
  },
  reviewer: {
    name: 'Reviewer',
    short: 'Layer 4',
    color: 'var(--new)',
    example: 'A data steward picked the right patient from the 3 nearest',
  },
  needs_review: {
    name: 'Needs review · low confidence',
    short: 'Waiting',
    color: 'var(--warn)',
    example: 'Shown in Needs review with the 3 nearest patients',
  },
  first_record: {
    name: 'No match yet',
    short: 'No match',
    color: 'var(--neu)',
    example: 'A hub enrollment with no therapy yet',
  },
};

export function layerTitle(layer: string) {
  const meta = LAYER_META[layer];
  if (!meta) return layer;
  if (layer === 'needs_review' || layer === 'first_record') return meta.name;
  return `${meta.short} · ${meta.name}`;
}

export function layerName(layer: string) {
  if (layer === 'first_record') return 'First record';
  return LAYER_META[layer]?.name || layer;
}

export function statusClass(status: string) {
  if (status === 'On therapy') return 'ok';
  if (status === 'Stopped') return 'neu';
  if (status === 'Never started') return 'bad';
  return 'warn';
}

export function SourcePill({ source }: { source: string }) {
  const meta = SRC[source] || { label: source, color: 'var(--muted)' };
  return (
    <span className="pill" style={{ background: `${meta.color}22`, color: meta.color }}>
      {meta.label}
    </span>
  );
}

export function SourceDots({ sources }: { sources: string[] }) {
  return (
    <span>
      {(['hub', 'pharmacy', 'claims'] as const).map((source) => (
        <i
          key={source}
          className={`srcdot${sources.includes(source) ? '' : ' off'}`}
          style={sources.includes(source) ? { background: SRC[source].color } : undefined}
          title={SRC[source].label}
        />
      ))}
      <span className="faint" style={{ fontSize: 12, marginLeft: 4 }}>
        {sources.length}/3
      </span>
    </span>
  );
}

const REF = /\b(?:HUB|SP|CLM)-\d+\b/g;

export function Rich({ text, onRef }: { text: string; onRef?: (ref: string) => void }) {
  const parts = text.split(REF);
  const refs = text.match(REF) || [];
  return (
    <>
      {parts.map((part, index) => (
        <span key={index}>
          {part}
          {refs[index] ? (
            <button className="cite" type="button" onClick={() => onRef?.(refs[index])}>
              {refs[index]}
            </button>
          ) : null}
        </span>
      ))}
    </>
  );
}

export function SummaryParagraph({ text, onRef }: { text: string; onRef?: (ref: string) => void }) {
  const labeled = text.match(/^(Dose|Pharmacy|Getting access|Watch):\s*([\s\S]*)$/);
  if (labeled) {
    return (
      <p>
        <b>{labeled[1]}:</b> <Rich text={labeled[2]} onRef={onRef} />
      </p>
    );
  }
  const status = text.match(/^((?:On therapy|Stopped|Never started|Waiting to start|Seen in claims)[^.]*\.)\s*([\s\S]*)$/);
  if (status) {
    return (
      <p>
        <b>{status[1]}</b> {status[2] ? <Rich text={status[2]} onRef={onRef} /> : null}
      </p>
    );
  }
  return (
    <p>
      <Rich text={text} onRef={onRef} />
    </p>
  );
}

export function Modal({
  title,
  children,
  footer,
  extra,
  onClose,
  tour,
}: {
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  extra?: ReactNode;
  onClose?: () => void;
  tour?: string;
}) {
  return (
    <div className="scrim" role="presentation" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" data-tour={tour} onClick={(event) => event.stopPropagation()}>
        <div className="modal-h">
          <h2>{title}</h2>
          {extra}
          {onClose ? (
            <button className="iconbtn x" type="button" onClick={onClose} aria-label="Close">
              <Icon name="x" />
            </button>
          ) : null}
        </div>
        <div className="modal-b">{children}</div>
        {footer ? <div className="modal-f">{footer}</div> : null}
      </div>
    </div>
  );
}

export function Drawer({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  return (
    <>
      <div className="dscrim" onClick={onClose} />
      <div className={`drawer${wide ? ' wide' : ''}`} role="dialog" aria-modal="true">
        <div className="drawer-h">
          <h2>{title}</h2>
          <button className="iconbtn x" type="button" onClick={onClose} aria-label="Close">
            <Icon name="x" />
          </button>
        </div>
        <div className="drawer-b">{children}</div>
      </div>
    </>
  );
}

export function Toast({ children, onDone }: { children: ReactNode; onDone: () => void }) {
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    const timer = window.setTimeout(() => done.current(), 4200);
    return () => window.clearTimeout(timer);
  }, []);
  return (
    <div className="toast" role="status">
      {children}
    </div>
  );
}
