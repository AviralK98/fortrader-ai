import { useEffect, useRef } from 'react';

/**
 * Track the pointer as two CSS custom properties on an element.
 *
 * Throttled to one write per animation frame. This runs beside a live
 * chart, and a mousemove handler that writes on every event is a
 * measurable cost for a decorative highlight.
 *
 * The listener is only attached when the effect is switched on, so the
 * setting removes the work rather than merely hiding the result.
 */
export function usePointerLight<T extends HTMLElement>(
  enabled: boolean,
): React.RefObject<T | null> {
  const ref = useRef<T>(null);

  useEffect(() => {
    const element = ref.current;

    if (!enabled || !element) return;

    let frame = 0;
    let x = 0;
    let y = 0;

    const write = (): void => {
      frame = 0;
      element.style.setProperty('--px', `${x}%`);
      element.style.setProperty('--py', `${y}%`);
    };

    const move = (event: MouseEvent): void => {
      const box = element.getBoundingClientRect();

      x = ((event.clientX - box.left) / box.width) * 100;
      y = ((event.clientY - box.top) / box.height) * 100;

      if (!frame) frame = requestAnimationFrame(write);
    };

    element.addEventListener('mousemove', move);

    return () => {
      element.removeEventListener('mousemove', move);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [enabled]);

  return ref;
}
