/**
 * Contracts shared between the Electron main process, the preload bridge
 * and the React renderer.
 *
 * These mirror the Pydantic models in `backend/fortrade/models.py`. When one
 * side changes, change both.
 */

export type AppStateValue =
  | 'STARTING'
  | 'FORTRADE_LOADING'
  | 'AUTH_REQUIRED'
  | 'CONNECTED'
  | 'MARKET_CLOSED'
  | 'BACKEND_ERROR'
  | 'FORTRADE_ERROR'
  | 'DISCONNECTED';

export type ComponentStatus = 'READY' | 'PENDING' | 'ERROR' | 'UNAVAILABLE';

export type AccountType = 'DEMO' | 'LIVE' | 'UNKNOWN';

export type Timeframe = 'M1' | 'M5' | 'M15' | 'M30' | 'H1' | 'H4' | 'D1';

export interface SystemStatus {
  state: AppStateValue;
  fortrade: ComponentStatus;
  analysis_engine: ComponentStatus;
  database: ComponentStatus;
  mcp: ComponentStatus;
  trading_enabled: boolean;
  last_snapshot_at: string | null;
  data_age_seconds: number | null;
  stale: boolean;
  detail: string | null;
  updated_at: string;
}

export interface Account {
  balance: number;
  equity: number;
  open_pnl: number;
  used_margin: number;
  available_margin: number;
  currency: string;
  account_type: AccountType;
  captured_at: string;
}

export interface Quote {
  symbol: string;
  sell: number;
  buy: number;
  change_percent: number | null;
  spread_points: number | null;
  quoted_at: string | null;
  captured_at: string;
}

export interface Position {
  symbol: string;
  direction: 'BUY' | 'SELL';
  amount: number;
  open_rate: number;
  current_rate: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  pnl: number | null;
  captured_at: string;
}

export interface SeriesCoverage {
  symbol: string;
  timeframe: Timeframe;
  count: number;
  first: string | null;
  last: string | null;
  /** True when enough bars are held for analysis to be considered reliable. */
  sufficient: boolean;
}

export type TrendDirection = 'BULLISH' | 'BEARISH' | 'MIXED' | 'UNKNOWN';
export type MomentumDirection = 'RISING' | 'FALLING' | 'NEUTRAL' | 'UNKNOWN';
export type VolatilityRegime = 'LOW' | 'NORMAL' | 'HIGH' | 'UNKNOWN';

export interface AnalysisIndicators {
  ema9: number | null;
  ema21: number | null;
  ema50: number | null;
  ema200: number | null;
  rsi14: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
  atr14: number | null;
  atr_percent: number | null;
  realised_volatility: number | null;
  vwap: number | null;
  vwap_available: boolean;
}

export interface AnalysisStructure {
  support: number | null;
  resistance: number | null;
  recent_high: number | null;
  recent_low: number | null;
  swing_high_count: number;
  swing_low_count: number;
}

export interface Analysis {
  symbol: string;
  timeframe: Timeframe;
  price: number | null;
  trend: TrendDirection;
  momentum: MomentumDirection;
  volatility_regime: VolatilityRegime;
  indicators: AnalysisIndicators;
  structure: AnalysisStructure;
  bars_used: number;
  bars_available: number;
  reliable: boolean;
  reasons: string[];
  warnings: string[];
  computed_at: string;
  last_bar_at: string | null;
}

export type Bias = 'LONG' | 'SHORT' | 'WAIT';

export interface Signal {
  symbol: string;
  timeframe: Timeframe;
  bias: Bias;
  /** Conviction 0–100. 50 means none. NOT a probability. */
  score: number;
  trend_score: number;
  momentum_score: number;
  structure_score: number;
  volatility_score: number;
  timeframe_score: number;
  net_direction: number;
  price: number | null;
  support: number | null;
  resistance: number | null;
  indicators: AnalysisIndicators;
  bars_used: number;
  reliable: boolean;
  reasons: string[];
  warnings: string[];
  created_at: string;
}

export interface TimeframeReading {
  timeframe: Timeframe;
  bias: Bias;
  score: number;
  net_direction: number;
  bars_used: number;
  weight: number;
  included: boolean;
  note: string | null;
}

export interface MultiTimeframe {
  symbol: string;
  readings: TimeframeReading[];
  agreement: number;
  combined_score: number;
  overall_bias: Bias;
  consensus: number;
  included_timeframes: Timeframe[];
  missing_timeframes: Timeframe[];
  reasons: string[];
  warnings: string[];
}

export interface BacktestMetrics {
  trades: number;
  wins: number;
  losses: number;
  breakeven: number;
  win_rate: number | null;
  average_win_r: number | null;
  average_loss_r: number | null;
  expectancy_r: number | null;
  profit_factor: number | null;
  max_drawdown_pct: number | null;
  max_consecutive_losses: number;
  total_r: number;
  /** False when too few trades exist for the figures to mean anything. */
  sufficient: boolean;
  minimum_trades: number;
  warnings: string[];
}

export interface BacktestResult {
  symbol: string;
  timeframe: Timeframe;
  strategy: string;
  bars_available: number;
  bars_tested: number;
  range_start: string | null;
  range_end: string | null;
  metrics: BacktestMetrics;
  ran: boolean;
  warnings: string[];
}

export interface PaperTrade {
  id: number;
  symbol: string;
  timeframe: Timeframe;
  direction: Bias;
  entry: number;
  stop: number;
  target: number | null;
  size: number;
  opened_at: string;
  closed_at: string | null;
  exit_price: number | null;
  pnl: number | null;
  r_multiple: number | null;
  entry_reason: string | null;
  status: 'OPEN' | 'CLOSED' | 'CANCELLED';
  current_price: number | null;
  unrealised_pnl: number | null;
  unrealised_r: number | null;
}

export interface PaperSummary {
  open_positions: number;
  closed_trades: number;
  starting_equity: number;
  realised_pnl: number;
  unrealised_pnl: number;
  equity: number;
  total_r: number;
  auto_open: boolean;
}

export interface PaperState {
  open: PaperTrade[];
  closed: PaperTrade[];
  summary: PaperSummary;
  metrics: BacktestMetrics;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatSend {
  available: boolean;
  reply: string | null;
  detail: string | null;
  /** What live state the answer was grounded in. */
  grounded_on: string[];
  /** "cli" (Claude Code subscription) or "api" (key). */
  provider: string | null;
}

export interface ChatStatus {
  available: boolean;
  provider: string | null;
  detail: string | null;
}

export interface ChartSelection {
  symbol: string;
  timeframe: Timeframe;
}

export interface Coverage {
  series: SeriesCoverage[];
  required: number;
  total_bars: number;
}

/** Where the Fortrade view should be placed, in CSS pixels. */
export interface ViewBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface UpdateState {
  status:
    | 'idle'
    | 'disabled'
    | 'checking'
    | 'current'
    | 'downloading'
    | 'ready'
    /** A newer version exists but this platform cannot install it itself. */
    | 'manual'
    | 'error';
  version?: string;
  percent?: number;
  detail?: string;
  /** Set only for 'manual': where the user downloads it themselves. */
  downloadUrl?: string;
}

/** Everything needed to point Claude Code at this installation. */
export interface McpSetup {
  /** Absolute path to the backend executable, or the dev interpreter. */
  command: string;
  args: string[];
  cwd?: string;
  /** Ready-to-paste JSON for the user's Claude config. */
  configJson: string;
  /** Where that JSON should go on this machine. */
  configPath: string;
  packaged: boolean;
}

/** Main-process runtime facts the UI needs at startup. */
export interface ShellInfo {
  backendUrl: string;
  backendReady: boolean;
  appVersion: string;
  /** Always false in this build. There is no execution capability. */
  tradingEnabled: false;
}

export interface FortradeViewState {
  url: string;
  loading: boolean;
  /** True once the authenticated trading UI is detected. */
  authenticated: boolean;
}

/**
 * The complete surface exposed to the renderer through `contextBridge`.
 * Nothing here can place, modify or close an order.
 */
export interface DesktopApi {
  getShellInfo(): Promise<ShellInfo>;

  setFortradeBounds(bounds: ViewBounds): void;
  setFortradeVisible(visible: boolean): void;
  reloadFortrade(): void;

  onStateChanged(cb: (state: AppStateValue, detail: string | null) => void): () => void;
  onFortradeViewChanged(cb: (state: FortradeViewState) => void): () => void;
  onBackendLog(cb: (line: string) => void): () => void;

  getMcpSetup(): Promise<McpSetup>;
  /** Writes the MCP entry to the user's Claude config, with their consent. */
  writeMcpConfig(): Promise<{ written: boolean; path: string; detail?: string }>;
  copyToClipboard(text: string): void;

  getUpdateState(): Promise<UpdateState>;
  checkForUpdates(): void;
  installUpdate(): void;
  onUpdateChanged(cb: (state: UpdateState) => void): () => void;
}

export const IPC = {
  getShellInfo: 'shell:get-info',
  setFortradeBounds: 'fortrade:set-bounds',
  setFortradeVisible: 'fortrade:set-visible',
  reloadFortrade: 'fortrade:reload',
  stateChanged: 'app:state-changed',
  fortradeViewChanged: 'fortrade:view-changed',
  backendLog: 'backend:log',
  getMcpSetup: 'mcp:get-setup',
  writeMcpConfig: 'mcp:write-config',
  copyToClipboard: 'shell:copy',
  getUpdateState: 'update:get-state',
  checkForUpdates: 'update:check',
  installUpdate: 'update:install',
  updateChanged: 'update:changed',
} as const;

export const FORTRADE_URL = 'https://ready.fortrade.com/';

/** Navigation outside these hosts is blocked inside the embedded view. */
export const FORTRADE_ALLOWED_HOSTS = [
  'fortrade.com',
  'ready.fortrade.com',
  'www.fortrade.com',
];
