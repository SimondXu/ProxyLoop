import { useCallback, useEffect, useRef, useState } from "react";

export type Speed = 1 | 4;

/** A clock on the bundle's t_ms: play, pause, 1×/4× and seek. It opens at the end (redesign §3.4); Play there starts from 0. */
export function usePlayback(endMs: number) {
  const [t, setT] = useState(endMs);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<Speed>(1);
  const tRef = useRef(endMs);

  const seek = useCallback((ms: number) => {
    tRef.current = ms;
    setT(ms);
  }, []);

  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const next = Math.min(endMs, tRef.current + (now - last) * speed);
      last = now;
      seek(next);
      if (next >= endMs) setPlaying(false);
      else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, speed, endMs, seek]);

  const toggle = () => {
    if (!playing && tRef.current >= endMs) seek(0);
    setPlaying(!playing);
  };
  return { t, playing, speed, setSpeed, seek, toggle };
}
