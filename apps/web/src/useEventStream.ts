import { useEffect, useRef, useState } from "react";
import { acceptFrames, closed, start, type Framed, type Stream } from "./liveState";
import { entry, paths, socketUrl, type Role } from "./liveApi";

const BATCH_MS = 50;

/**
 * Frames over /ws/live (the user's shell: events) or /ws/rep (the rep page:
 * rebuilt frames with the rep stream's own seq); both are dense from 0.
 * `parse` must be a module-level function.
 * A reconnect is the user's click and resumes at the last seq + 1; nothing
 * reconnects or retries on its own. Frames are taken in batches of BATCH_MS,
 * so a catch-up burst of thousands is one copy and one render, not one each.
 */
export function useEventStream<T extends Framed>(role: Role, id: string, parse: (text: string) => T | string) {
  const [stream, setStream] = useState<Stream<T>>(start<T>);
  const [attempt, setAttempt] = useState(0);
  const current = useRef<Stream<T>>(start<T>());

  useEffect(() => {
    let mine = true;
    let batch: (T | string)[] = [];
    let timer: ReturnType<typeof setTimeout> | undefined;
    const set = (s: Stream<T>) => {
      current.current = s;
      setStream(s);
    };
    const path = role === "live" ? paths.liveSocket : paths.repSocket;
    const ws = new WebSocket(socketUrl(path(id, current.current.next)));
    const flush = () => {
      clearTimeout(timer);
      timer = undefined;
      // /ws/live frames are events: each must belong to the run being watched.
      const next = acceptFrames(current.current, batch, role === "live" ? id : undefined);
      batch = [];
      set(next);
      if (next.phase === "error") ws.close();
    };
    ws.onopen = () => mine && set({ ...current.current, phase: "open", message: "" });
    ws.onmessage = (m: MessageEvent) => {
      if (!mine) return;
      batch.push(parse(String(m.data)));
      timer ??= setTimeout(flush, BATCH_MS);
    };
    ws.onclose = (c) => {
      if (!mine) return;
      if (timer !== undefined) flush();
      set(closed(current.current, c.code, c.reason, entry(role, id)));
    };
    return () => {
      mine = false;
      clearTimeout(timer);
      ws.close();
    };
  }, [role, id, parse, attempt]);

  const reconnect = () => {
    current.current = { ...current.current, phase: "connecting", message: "" };
    setStream(current.current);
    setAttempt((a) => a + 1);
  };
  return { stream, reconnect };
}
