import { useEffect } from 'react';

/**
 * Let the wave bands rise toward the pointer.
 *
 * Writes two normalised values to the root element: how high the cursor
 * is in the window, and how far across. The waves read them from a
 * `transform`, and a long transition on that transform is what makes
 * them glide up rather than snap — the pointer sets a target, the
 * easing decides how it is reached.
 *
 * Throttled to one write per animation frame. This runs beside a live
 * chart, and writing on every mousemove is a real cost for a background
 * effect. The listener is only attached when the setting is on, so
 * switching it off removes the work rather than hiding the result.
 */
export function usePointerLift(enabled: boolean): void {
  useEffect(() => {
    const root = document.documentElement;

    if (!enabled) {
      // Settle back to rest rather than freezing wherever it stopped.
      root.style.setProperty('--wave-lift', '0');
      root.style.setProperty('--wave-shift', '0.5');
      return;
    }

    let frame = 0;
    let lift = 0;
    let shift = 0.5;

    const write = (): void => {
      frame = 0;
      root.style.setProperty('--wave-lift', lift.toFixed(3));
      root.style.setProperty('--wave-shift', shift.toFixed(3));
    };

    const move = (event: MouseEvent): void => {
      // 1 at the top of the window, 0 at the bottom: the waves rise as
      // the pointer does.
      lift = 1 - event.clientY / window.innerHeight;
      shift = event.clientX / window.innerWidth;

      if (!frame) frame = requestAnimationFrame(write);
    };

    window.addEventListener('mousemove', move);

    return () => {
      window.removeEventListener('mousemove', move);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [enabled]);
}
