import { useEffect, useRef, useState } from "react";
import { acceptFrame, closed, start, type Framed, type Stream } from "./liveState";
import { entry, paths, socketUrl, type Role } from "./liveApi";

/**
 * Frames over /ws/live (the user's shell: events, dense) or /ws/rep (the rep
 * page: rebuilt frames, original seqs). `parse` must be a module-level function.
 * A reconnect is the user's click and resumes at the last seq + 1; nothing
 * reconnects or retries on its own.
 */
export function useEventStream<T extends Framed>(role: Role, id: string, parse: (text: string) => T | string) {
  const [stream, setStream] = useState<Stream<T>>(start<T>);
  const [attempt, setAttempt] = useState(0);
  const current = useRef<Stream<T>>(start<T>());

  useEffect(() => {
    let mine = true;
    const set = (s: Stream<T>) => {
      current.current = s;
      setStream(s);
    };
    const path = role === "live" ? paths.liveSocket : paths.repSocket;
    const ws = new WebSocket(socketUrl(path(id, current.current.next)));
    ws.onopen = () => mine && set({ ...current.current, phase: "open", message: "" });
    ws.onmessage = (m: MessageEvent) => {
      if (!mine) return;
      const next = acceptFrame(current.current, parse(String(m.data)), role === "live");
      set(next);
      if (next.phase === "error") ws.close();
    };
    ws.onclose = (c) => mine && set(closed(current.current, c.code, c.reason, entry(role, id)));
    return () => {
      mine = false;
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
