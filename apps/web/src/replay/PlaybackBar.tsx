// The replay's PlaybackBar (redesign §3.4): Play/Pause, 1×/4×, the "Timeline"
// slider with its markers above it, the chapter chips and the mm:ss clock. The
// markers and chapters are marks.ts's, from the full log; a chapter the run
// never reached is shown disabled rather than hidden.
import type { usePlayback, Speed } from "../usePlayback";
import { Button } from "../ui/Button";
import { mmss, type Chapter, type Mark } from "./marks";

type Props = { clock: ReturnType<typeof usePlayback>; end: number; marks: Mark[]; chapters: Chapter[] };

export function PlaybackBar({ clock, end, marks, chapters }: Props) {
  const at = (ms: number) => `${end > 0 ? (ms / end) * 100 : 0}%`;
  return (
    <section className="pl-playback" aria-label="Playback">
      <div className="pl-pb-row">
        <Button variant="primary" onClick={clock.toggle}>
          {clock.playing ? "Pause" : "Play"}
        </Button>
        {([1, 4] as Speed[]).map((s) => (
          <button key={s} type="button" className="pl-pb-speed" aria-pressed={clock.speed === s} onClick={() => clock.setSpeed(s)}>
            {s}×
          </button>
        ))}
        <div className="pl-pb-track">
          <ol className="pl-pb-marks" aria-label="Markers">
            {marks.map((m, i) => (
              <li key={i} className={`pl-pb-mark pl-pb-mark-${m.kind}`} style={{ left: at(m.t_ms) }} title={`${m.label} ${mmss(m.t_ms)}`}>
                <span className="pl-sr">
                  {m.label} {mmss(m.t_ms)}
                </span>
              </li>
            ))}
          </ol>
          <input
            type="range"
            aria-label="Timeline"
            min={0}
            max={end}
            value={Math.round(clock.t)}
            onChange={(e) => clock.seek(Number(e.target.value))}
          />
        </div>
        <output aria-label="Clock" className="pl-pb-clock">
          {mmss(clock.t)} / {mmss(end)}
        </output>
      </div>
      <ul className="pl-pb-chapters" aria-label="Chapters">
        {chapters.map((c) => (
          <li key={c.name}>
            <button type="button" disabled={c.t_ms === null} onClick={() => c.t_ms !== null && clock.seek(c.t_ms)}>
              {c.name}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
