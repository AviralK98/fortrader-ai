import type { JSX } from 'react';

import type { ComponentStatus, SystemStatus } from '../../../shared/types';

interface Props {
  status: SystemStatus | undefined;
  backendReachable: boolean;
}

function Dot({ state }: { state: ComponentStatus }): JSX.Element {
  return <span className={`dot dot--${state.toLowerCase()}`} aria-hidden="true" />;
}

function Indicator({
  label,
  state,
  value,
}: {
  label: string;
  state: ComponentStatus;
  value: string;
}): JSX.Element {
  return (
    <div className="indicator" title={`${label}: ${value}`}>
      <span className="indicator__label">{label}</span>
      <Dot state={state} />
      <span className="indicator__value">{value}</span>
    </div>
  );
}

/** Formats data age so the UI never implies stale data is live. */
function freshness(status: SystemStatus | undefined): {
  state: ComponentStatus;
  value: string;
} {
  if (!status || status.last_snapshot_at === null) {
    return { state: 'PENDING', value: 'No data yet' };
  }

  const age = status.data_age_seconds ?? 0;

  if (status.stale) {
    return { state: 'ERROR', value: `Stale · ${age.toFixed(0)}s old` };
  }

  return { state: 'READY', value: `Live · ${age.toFixed(0)}s ago` };
}

export function StatusStrip({ status, backendReachable }: Props): JSX.Element {
  const data = freshness(status);

  return (
    <header className="status-strip">
      <div className="brand">
        <span className="brand__mark" aria-hidden="true" />
        <h1>FORTRADER AI</h1>
        <span className="badge badge--research">RESEARCH ONLY</span>
      </div>

      <div className="indicators">
        <Indicator
          label="Fortrade"
          state={status?.fortrade ?? 'PENDING'}
          value={status?.state.replace(/_/g, ' ') ?? 'Starting'}
        />
        <Indicator
          label="Backend"
          state={backendReachable ? 'READY' : 'ERROR'}
          value={backendReachable ? 'Connected' : 'Unreachable'}
        />
        <Indicator
          label="Analysis"
          state={status?.analysis_engine ?? 'PENDING'}
          value={status?.analysis_engine === 'READY' ? 'Ready' : 'Pending'}
        />
        <Indicator label="Data" state={data.state} value={data.value} />
      </div>
    </header>
  );
}
