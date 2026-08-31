import { useEffect } from 'react';
import type { JSX } from 'react';
import { useQuery } from '@tanstack/react-query';

import { AccountBar } from './components/AccountBar';
import { AnalysisPanel } from './components/AnalysisPanel';
import { FortradeSlot } from './components/FortradeSlot';
import { StatusStrip } from './components/StatusStrip';
import { BackendNotReadyError, backend } from './services/backend';
import { connectShellEvents } from './store/shell';

/** Polling cadence for backend state. Fast enough to feel live, cheap. */
const STATUS_INTERVAL = 2_000;
const ACCOUNT_INTERVAL = 3_000;

export function App(): JSX.Element {
  useEffect(() => connectShellEvents(), []);

  const status = useQuery({
    queryKey: ['status'],
    queryFn: backend.status,
    refetchInterval: STATUS_INTERVAL,
    retry: false,
  });

  const account = useQuery({
    queryKey: ['account'],
    queryFn: backend.account,
    refetchInterval: ACCOUNT_INTERVAL,
    retry: false,
  });

  const quotes = useQuery({
    queryKey: ['quotes'],
    queryFn: backend.quotes,
    refetchInterval: ACCOUNT_INTERVAL,
    retry: false,
  });

  const positions = useQuery({
    queryKey: ['positions'],
    queryFn: backend.positions,
    refetchInterval: ACCOUNT_INTERVAL,
    retry: false,
  });

  // Coverage changes only when a chart is opened; polling can be lazy.
  const coverage = useQuery({
    queryKey: ['coverage'],
    queryFn: backend.coverage,
    refetchInterval: 5_000,
    retry: false,
  });

  const paper = useQuery({
    queryKey: ['paper'],
    queryFn: backend.paper,
    refetchInterval: 5_000,
    retry: false,
  });

  // Analysis follows whichever chart is selected in Fortrade.
  const chart = useQuery({
    queryKey: ['chart'],
    queryFn: backend.chart,
    refetchInterval: 5_000,
    retry: false,
  });

  const analysis = useQuery({
    queryKey: ['analysis', chart.data?.symbol, chart.data?.timeframe],
    queryFn: () =>
      backend.analysis(chart.data!.symbol, chart.data!.timeframe),
    enabled: Boolean(chart.data?.symbol),
    refetchInterval: 10_000,
    retry: false,
  });

  const signal = useQuery({
    queryKey: ['signal', chart.data?.symbol, chart.data?.timeframe],
    queryFn: () => backend.signal(chart.data!.symbol, chart.data!.timeframe),
    enabled: Boolean(chart.data?.symbol),
    refetchInterval: 10_000,
    retry: false,
  });

  const multi = useQuery({
    queryKey: ['timeframes', chart.data?.symbol],
    queryFn: () => backend.timeframes(chart.data!.symbol),
    enabled: Boolean(chart.data?.symbol),
    refetchInterval: 15_000,
    retry: false,
  });

  // A 503 means "not observed yet", which is a normal startup condition
  // rather than a failure to report.
  const accountPending =
    account.isPending || account.error instanceof BackendNotReadyError;

  return (
    <div className="app">
      <StatusStrip
        status={status.data}
        backendReachable={!status.isError}
      />

      <main className="workspace">
        <FortradeSlot />
        <AnalysisPanel
          status={status.data}
          quotes={quotes.data}
          positions={positions.data}
          coverage={coverage.data}
          analysis={analysis.data}
          signal={signal.data}
          multi={multi.data}
          chart={chart.data}
          paper={paper.data}
          pending={accountPending}
        />
      </main>

      <AccountBar account={account.data} pending={accountPending} />
    </div>
  );
}
