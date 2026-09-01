import { useRef, useState, type JSX } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';

import type { ChatMessage, ChatSend, ChartSelection } from '../../../shared/types';
import { backend } from '../services/backend';

interface Props {
  chart: ChartSelection | undefined;
}

const SUGGESTIONS = [
  'What is the current signal telling me?',
  'What argues against this setup?',
  'What does ATR mean here?',
  'How well has this system actually performed?',
] as const;

/** How the answer was obtained, in the user's terms rather than ours. */
const PROVIDER_LABEL: Record<string, string> = {
  cli: 'via Claude Code — no API key, no per-question cost',
  api: 'via the Anthropic API — billed to your key',
};

/**
 * Scoped chat about the user's own analysis.
 *
 * Deliberately not a general assistant: the backend injects live
 * deterministic state on every turn and the system prompt declines
 * anything outside this application's market analysis.
 */
export function ChatPanel({ chart }: Props): JSX.Element {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  // Cheap: the backend caches its CLI probe, so this is not a spawn per
  // render. Refetched on mount so installing Claude Code takes effect on
  // the next visit rather than needing a restart.
  const status = useQuery({
    queryKey: ['chat-status'],
    queryFn: () => backend.chatStatus(),
    staleTime: 30_000,
  });

  const send = useMutation({
    mutationFn: (text: string): Promise<ChatSend> =>
      backend.chat({
        message: text,
        history: messages,
        symbol: chart?.symbol ?? 'GBP/USD',
        timeframe: chart?.timeframe ?? 'M5',
      }),
    onSuccess: (reply, text) => {
      if (reply.available && reply.reply) {
        setMessages((prev) => [
          ...prev,
          { role: 'user', content: text },
          { role: 'assistant', content: reply.reply as string },
        ]);
        setNotice(null);
      } else {
        setNotice(reply.detail ?? 'No reply.');
      }

      requestAnimationFrame(() =>
        endRef.current?.scrollIntoView({ behavior: 'smooth' }),
      );
    },
    onError: (error) => setNotice(String(error)),
  });

  const submit = (text: string) => {
    const trimmed = text.trim();

    if (!trimmed || send.isPending) return;

    setDraft('');
    send.mutate(trimmed);
  };

  return (
    <div className="chat">
      <div className="chat__log">
        {messages.length === 0 && !send.isPending && (
          <div className="chat__intro">
            <p>
              Ask about the signal, an indicator, or why a setup is or is not
              tradeable. Answers are grounded in your live data.
            </p>
            {status.data && !status.data.available && (
              <p className="chat__notice">{status.data.detail}</p>
            )}
            <div className="chat__suggestions">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="chat__suggestion"
                  onClick={() => submit(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={`${m.role}-${i}`} className={`chat__msg chat__msg--${m.role}`}>
            {m.content}
          </div>
        ))}

        {send.isPending && (
          <div className="chat__msg chat__msg--pending">
            <span className="chat__dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            Reading your live data…
          </div>
        )}

        <div ref={endRef} />
      </div>

      {notice && <div className="chat__notice">{notice}</div>}

      <form
        className="chat__composer"
        onSubmit={(e) => {
          e.preventDefault();
          submit(draft);
        }}
      >
        <input
          type="text"
          className="chat__input"
          value={draft}
          maxLength={2000}
          placeholder={
            chart ? `Ask about ${chart.symbol} ${chart.timeframe}…` : 'Ask…'
          }
          onChange={(e) => setDraft(e.target.value)}
          disabled={send.isPending}
        />
        <button
          type="submit"
          className="button"
          disabled={send.isPending || !draft.trim()}
        >
          Ask
        </button>
      </form>

      <p className="score-caveat">
        Scoped to this application&apos;s analysis. It cannot forecast price —
        no system can — and nothing it says is advice.
        {status.data?.available && status.data.provider && (
          <> {PROVIDER_LABEL[status.data.provider] ?? ''}</>
        )}
      </p>
    </div>
  );
}
