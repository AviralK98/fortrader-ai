import { useEffect, useState, type JSX } from 'react';

import { usePointerLift } from '../usePointerLift';

/**
 * Wave bands across the bottom of the window.
 *
 * Three layers at different heights, speeds and opacities, which is what
 * reads as depth rather than as one moving shape. They drift on their
 * own and rise toward the pointer.
 *
 * The colour comes from CSS so the accent and the preset drive it; the
 * shape comes from an SVG used as a mask. Baking the fill into the SVG
 * would have been simpler and would have frozen the colour, leaving the
 * waves the wrong hue in five of the six presets.
 */
export function Waves(): JSX.Element {
  const [follow, setFollow] = useState(
    () => document.documentElement.dataset.pointer !== 'off',
  );

  // The setting is written to the root element by appearance.ts, so the
  // toggle takes effect immediately instead of on the next launch.
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setFollow(document.documentElement.dataset.pointer !== 'off');
    });

    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-pointer'],
    });

    return () => observer.disconnect();
  }, []);

  usePointerLift(follow);

  return (
    <div className="waves" aria-hidden="true">
      <div className="waves__lift">
        <span className="waves__layer waves__layer--back" />
        <span className="waves__layer waves__layer--mid" />
        <span className="waves__layer waves__layer--front" />
      </div>
    </div>
  );
}
