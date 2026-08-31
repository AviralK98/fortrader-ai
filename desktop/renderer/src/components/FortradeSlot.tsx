import { useEffect, useRef } from 'react';
import type { JSX } from 'react';

import { useShellStore } from '../store/shell';

/**
 * Reserves the region where the Fortrade `WebContentsView` is painted.
 *
 * The view is a native sibling layered above this renderer, so this element
 * never contains Fortrade's DOM — it only measures where the view belongs
 * and reports that to the main process.
 */
export function FortradeSlot(): JSX.Element {
  const ref = useRef<HTMLDivElement>(null);
  const fortrade = useShellStore((s) => s.fortrade);

  useEffect(() => {
    const element = ref.current;

    if (!element) return;

    const report = () => {
      const rect = element.getBoundingClientRect();

      window.desktop.setFortradeBounds({
        x: rect.left,
        y: rect.top,
        width: rect.width,
        height: rect.height,
      });
    };

    report();

    const observer = new ResizeObserver(report);
    observer.observe(element);

    window.addEventListener('resize', report);

    return () => {
      observer.disconnect();
      window.removeEventListener('resize', report);
    };
  }, []);

  return (
    <div className="fortrade-slot" ref={ref}>
      {fortrade.loading && (
        <div className="fortrade-slot__placeholder">
          <span className="spinner" aria-hidden="true" />
          <p>Loading Web Fortrader…</p>
        </div>
      )}
    </div>
  );
}
