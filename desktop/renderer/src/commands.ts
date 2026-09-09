/**
 * A tiny event bus between the command palette and the panels it drives.
 *
 * The view selection lives in AnalysisPanel and the appearance lives in
 * AppearancePanel, both as ordinary React state. The palette needs to
 * change either, and lifting both into a shared store to support one
 * overlay would be a large refactor for a small feature.
 *
 * Events keep each panel the single owner of its own state: the palette
 * asks, the panel decides, and nothing has to know the palette exists
 * beyond one listener.
 */

export const VIEW_EVENT = 'fortrader:view';
export const APPEARANCE_EVENT = 'fortrader:appearance';

export function requestView(id: string): void {
  window.dispatchEvent(new CustomEvent(VIEW_EVENT, { detail: id }));
}

export function requestAppearance(patch: Record<string, unknown>): void {
  window.dispatchEvent(new CustomEvent(APPEARANCE_EVENT, { detail: patch }));
}

/** Subscribe to one of the events above; returns an unsubscribe. */
export function onCommand<T>(
  name: string,
  handler: (detail: T) => void,
): () => void {
  const listener = (event: Event): void => {
    handler((event as CustomEvent<T>).detail);
  };

  window.addEventListener(name, listener);

  return () => window.removeEventListener(name, listener);
}

/**
 * Rank a command against what has been typed.
 *
 * A plain substring test is too strict — nobody types "background
 * motion" in full — and a full fuzzy library is more than this needs.
 * Subsequence matching finds "bgm" in "Background motion", and the
 * scoring prefers a prefix hit so typing "sig" puts Signal first rather
 * than something that merely contains those letters in order.
 *
 * Returns null when it does not match at all.
 */
export function score(text: string, query: string): number | null {
  if (!query) return 0;

  const haystack = text.toLowerCase();
  const needle = query.toLowerCase().trim();

  if (!needle) return 0;

  if (haystack.startsWith(needle)) return 1000;

  const index = haystack.indexOf(needle);

  if (index >= 0) return 500 - index;

  // Subsequence: every character in order, not necessarily adjacent.
  let position = 0;
  let gaps = 0;

  for (const character of needle) {
    const found = haystack.indexOf(character, position);

    if (found === -1) return null;

    gaps += found - position;
    position = found + 1;
  }

  return 200 - Math.min(gaps, 199);
}
