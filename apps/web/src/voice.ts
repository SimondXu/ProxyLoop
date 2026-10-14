// The call, spoken (S1-SYS-122). Presentation only: it reads the call lines the page already shows
// (conversation.ts: the Agent's text_heard, never text_generated; the Rep's utt.final) and says them
// aloud with Kokoro-82M in the browser (kokoro-js, loaded only after the user turns sound on).
// It emits and changes no event.
import type { Line } from "./conversation";

export type Voice = "agent" | "rep";
export type SpeakItem = { id: string; speaker: Voice; text: string };

/** The call's spoken lines, in order: the Agent's heard lines and the Rep's lines; the call's own markers are not spoken. */
export function speakItems(call: Line[]): SpeakItem[] {
  const items: SpeakItem[] = [];
  for (const l of call) {
    const text = l.text.trim();
    if ((l.who === "agent" || l.who === "rep") && text) items.push({ id: l.id, speaker: l.who, text });
  }
  return items;
}

/** The items not in `seen` yet, in order; they join `seen`, so a re-render or a reconnect never yields one twice. */
export function fresh(items: SpeakItem[], seen: Set<string>): SpeakItem[] {
  const out = items.filter((i) => !seen.has(i.id));
  for (const i of out) seen.add(i.id);
  return out;
}

const MODEL = "onnx-community/Kokoro-82M-v1.0-ONNX";
const VOICE_OF = { agent: "af_heart", rep: "am_michael" } as const; // an American woman for the agent, a man for the rep

type Tts = { generate: (text: string, o: { voice: (typeof VOICE_OF)[Voice] }) => Promise<{ audio: Float32Array; sampling_rate: number }> };

let model: Promise<Tts> | null = null;
/** The model, loaded once (the browser caches its files). A failed load is forgotten, so turning sound on again retries. */
function load(): Promise<Tts> {
  model ??= import("kokoro-js")
    .then(({ KokoroTTS }) => KokoroTTS.from_pretrained(MODEL, { dtype: "q8", device: "gpu" in navigator ? "webgpu" : "wasm" }))
    .catch((e: unknown) => {
      model = null;
      throw e;
    });
  return model;
}

/**
 * Speaks items one at a time, in the order given. Each is synthesised once (the next while the
 * current one plays); stop() ends the audio at once and drops what is queued.
 * Create it in a click handler: a browser lets audio start only after a user gesture.
 */
export class Speaker {
  private ctx = new AudioContext();
  private epoch = 0; // stop() moves it on: work begun under an older one is dropped
  private synth: Promise<unknown> = Promise.resolve();
  private play: Promise<unknown> = Promise.resolve();
  private current: AudioBufferSourceNode | null = null;
  readonly ready: Promise<void>;

  constructor(private onError: (message: string) => void) {
    this.ready = Promise.all([load(), this.ctx.resume()]).then(() => undefined);
  }

  say(items: SpeakItem[]): void {
    const epoch = this.epoch;
    for (const item of items) {
      const clip = this.synth.then(async () => {
        if (epoch !== this.epoch) return null;
        return (await load()).generate(item.text, { voice: VOICE_OF[item.speaker] });
      });
      this.synth = clip.catch(() => null); // its failure is reported once, by the playback below
      this.play = this.play
        .then(async () => {
          const audio = (await clip) as Awaited<ReturnType<Tts["generate"]>> | null;
          if (audio && epoch === this.epoch) await this.out(audio, epoch);
        })
        .catch((e: unknown) => this.fail(e));
    }
  }

  private out(audio: { audio: Float32Array; sampling_rate: number }, epoch: number): Promise<void> {
    return new Promise((done) => {
      const buf = this.ctx.createBuffer(1, audio.audio.length, audio.sampling_rate);
      buf.copyToChannel(new Float32Array(audio.audio), 0);
      const src = this.ctx.createBufferSource();
      src.buffer = buf;
      src.connect(this.ctx.destination);
      src.onended = () => done();
      if (epoch !== this.epoch) return done();
      this.current = src;
      src.start();
    });
  }

  private fail(e: unknown): void {
    console.warn("voice: speech failed", e);
    this.onError(`Voice stopped: ${e instanceof Error ? e.message : String(e)}`);
  }

  stop(): void {
    this.epoch += 1;
    this.synth = Promise.resolve();
    this.play = Promise.resolve();
    try {
      this.current?.stop();
    } catch {
      // already ended
    }
    this.current = null;
    void this.ctx.close().catch(() => undefined);
  }
}
