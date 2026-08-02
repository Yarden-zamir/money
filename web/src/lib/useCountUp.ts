import { useEffect, useRef, useState } from "react";

/**
 * Animates a number up to its value.
 *
 * Only for figures a person reads as a headline — the ready-to-assign total. A column of
 * amounts all counting at once would be noise, and a number that is still moving cannot be
 * compared against another one.
 *
 * Returns the target immediately when the viewer prefers reduced motion, or when the value is
 * not a finite number.
 */
export function useCountUp(target: number, durationMs = 900): number {
  // Starts at zero, not at the target. Seeding `previous` with the target made the first
  // render a zero-distance animation, so the very run this exists for never happened.
  const [value, setValue] = useState(0);
  const previous = useRef(0);

  useEffect(() => {
    if (!Number.isFinite(target)) {
      setValue(target);
      return;
    }

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      previous.current = target;
      setValue(target);
      return;
    }

    const from = previous.current;
    const distance = target - from;
    if (distance === 0) return;

    let frame = 0;
    const started = performance.now();

    const tick = (now: number) => {
      const progress = Math.min(1, (now - started) / durationMs);
      // easeOutCubic: quick to start, settling gently rather than stopping dead.
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(from + distance * eased);

      if (progress < 1) frame = requestAnimationFrame(tick);
      else previous.current = target;
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, durationMs]);

  return value;
}
