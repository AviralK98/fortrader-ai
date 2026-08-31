/**
 * Development-only network observation for the Fortrade view.
 *
 * Enabled with `FORTRADER_DUMP_NET=1`. Attaches `webContents.debugger` to
 * the view we already host and records metadata about traffic the
 * authenticated session receives, so we can find where OHLC history
 * actually arrives.
 *
 * Strictly passive. It observes; it never issues a request, replays one,
 * crafts one, or touches an endpoint the page did not call itself.
 *
 * Everything recorded passes through the redactor first — WebSocket frames
 * and JSON bodies routinely carry session tokens.
 */

import { writeFileSync } from 'node:fs';
import type { WebContents } from 'electron';

import { createLogger, redactText } from './logging';

const log = createLogger('network-probe');

/** URL fragments that plausibly carry chart or price history. */
const INTERESTING_URL = /(chart|candle|histor|ohlc|bar|period|timeseries|rate|quote|price|feed|market)/i;

const MAX_BODY_CHARS = 4_000;
const MAX_FRAME_CHARS = 1_200;
const MAX_RECORDS = 400;

interface HttpRecord {
  kind: 'http';
  url: string;
  mimeType: string;
  status: number;
  bodyPreview?: string;
  bodyLength?: number;
  error?: string;
}

interface SocketRecord {
  kind: 'ws-created' | 'ws-frame-received' | 'ws-frame-sent';
  url?: string;
  opcode?: number;
  length?: number;
  preview?: string;
}

type Record_ = HttpRecord | SocketRecord;

export function isNetworkProbeEnabled(): boolean {
  return process.env.FORTRADER_DUMP_NET === '1';
}

export class NetworkProbe {
  private readonly records: Record_[] = [];
  private readonly pending = new Map<
    string,
    { url: string; mimeType: string; status: number }
  >();

  private attached = false;

  constructor(private readonly contents: WebContents) {}

  start(): void {
    if (this.attached) return;

    try {
      this.contents.debugger.attach('1.3');
      this.attached = true;
    } catch (error) {
      log.error('Could not attach debugger', { error: String(error) });
      return;
    }

    this.contents.debugger.on('message', (_event, method, params) => {
      try {
        this.handle(method, params as Record<string, unknown>);
      } catch (error) {
        log.debug('Probe handler failed', { method, error: String(error) });
      }
    });

    void this.contents.debugger.sendCommand('Network.enable', {
      maxTotalBufferSize: 32 * 1024 * 1024,
      maxResourceBufferSize: 8 * 1024 * 1024,
    });

    log.info('Network probe attached (passive observation only)');
  }

  private handle(method: string, params: Record<string, unknown>): void {
    if (this.records.length >= MAX_RECORDS) return;

    if (method === 'Network.responseReceived') {
      const response = params.response as
        | { url?: string; mimeType?: string; status?: number }
        | undefined;

      const requestId = params.requestId as string | undefined;

      if (!response?.url || !requestId) return;

      this.pending.set(requestId, {
        url: response.url,
        mimeType: response.mimeType ?? '',
        status: response.status ?? 0,
      });

      return;
    }

    if (method === 'Network.loadingFinished') {
      const requestId = params.requestId as string | undefined;

      if (!requestId) return;

      const meta = this.pending.get(requestId);
      this.pending.delete(requestId);

      if (!meta) return;

      const worthBody =
        INTERESTING_URL.test(meta.url) || /json/i.test(meta.mimeType);

      if (!worthBody) return;

      void this.captureBody(requestId, meta);

      return;
    }

    if (method === 'Network.webSocketCreated') {
      this.records.push({
        kind: 'ws-created',
        url: redactText(String(params.url ?? '')),
      });

      return;
    }

    if (
      method === 'Network.webSocketFrameReceived' ||
      method === 'Network.webSocketFrameSent'
    ) {
      const response = params.response as
        | { opcode?: number; payloadData?: string }
        | undefined;

      const payload = response?.payloadData ?? '';

      this.records.push({
        kind:
          method === 'Network.webSocketFrameReceived'
            ? 'ws-frame-received'
            : 'ws-frame-sent',
        opcode: response?.opcode,
        length: payload.length,
        preview: redactText(payload.slice(0, MAX_FRAME_CHARS)),
      });
    }
  }

  private async captureBody(
    requestId: string,
    meta: { url: string; mimeType: string; status: number },
  ): Promise<void> {
    try {
      const result = (await this.contents.debugger.sendCommand(
        'Network.getResponseBody',
        { requestId },
      )) as { body?: string; base64Encoded?: boolean };

      const body = result.base64Encoded ? '[base64]' : (result.body ?? '');

      this.records.push({
        kind: 'http',
        url: redactText(meta.url),
        mimeType: meta.mimeType,
        status: meta.status,
        bodyLength: body.length,
        bodyPreview: redactText(body.slice(0, MAX_BODY_CHARS)),
      });
    } catch (error) {
      this.records.push({
        kind: 'http',
        url: redactText(meta.url),
        mimeType: meta.mimeType,
        status: meta.status,
        error: String(error),
      });
    }
  }

  write(outputPath: string): void {
    const summary = {
      capturedAt: new Date().toISOString(),
      totalRecords: this.records.length,
      websocketUrls: this.records
        .filter((r) => r.kind === 'ws-created')
        .map((r) => (r as SocketRecord).url),
      httpUrls: Array.from(
        new Set(
          this.records
            .filter((r): r is HttpRecord => r.kind === 'http')
            .map((r) => r.url.split('?')[0]),
        ),
      ),
      records: this.records,
    };

    writeFileSync(outputPath, JSON.stringify(summary, null, 2), 'utf8');

    log.info('Network probe written', {
      path: outputPath,
      records: this.records.length,
    });
  }

  stop(): void {
    if (!this.attached) return;

    try {
      this.contents.debugger.detach();
    } catch {
      // Already gone.
    }

    this.attached = false;
  }
}
