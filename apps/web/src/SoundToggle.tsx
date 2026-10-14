// The live call's "Sound" switch (S1-SYS-122): off by default; on, the call's new lines are spoken (voice.ts).
import { useEffect, useMemo, useRef, useState } from "react";
import { conversation } from "./conversation";
import type { Ev } from "./replay";
import { fresh, speakItems, Speaker } from "./voice";

type Phase = "off" | "loading" | "on";

export function useVoice(events: Ev[]) {
  const [phase, setPhase] = useState<Phase>("off");
  const [error, setError] = useState("");
  const items = useMemo(() => speakItems(conversation(events).call), [events]);
  const seen = useRef(new Set<string>());
  const speaker = useRef<Speaker | null>(null);

  const off = () => {
    speaker.current?.stop();
    speaker.current = null;
    setPhase("off");
  };
  const on = () => {
    setError("");
    setPhase("loading");
    seen.current = new Set(items.map((i) => i.id)); // only lines that arrive from now on are spoken
    try {
      const s = new Speaker((m) => setError(m));
      speaker.current = s;
      s.ready.then(
        () => speaker.current === s && setPhase("on"),
        (e: unknown) => {
          console.warn("voice: could not start", e);
          if (speaker.current !== s) return;
          off();
          setError(`Sound unavailable: ${e instanceof Error ? e.message : String(e)}`);
        },
      );
    } catch (e) {
      console.warn("voice: could not start", e);
      off();
      setError(`Sound unavailable: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  useEffect(() => {
    if (phase === "on") speaker.current?.say(fresh(items, seen.current));
  }, [items, phase]);
  useEffect(() => () => speaker.current?.stop(), []);

  return { phase, error, toggle: () => (phase === "off" ? on() : off()) };
}

export function SoundToggle({ voice }: { voice: ReturnType<typeof useVoice> }) {
  return (
    <>
      <label>
        <input type="checkbox" checked={voice.phase !== "off"} onChange={voice.toggle} /> Sound
      </label>
      {voice.phase === "loading" && <span className="meta" role="status">Loading voice…</span>}
      {voice.error && <span className="meta" role="alert">{voice.error}</span>}
    </>
  );
}
