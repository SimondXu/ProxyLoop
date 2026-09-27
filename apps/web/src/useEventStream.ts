import { useEffect, useRef, useState } from "react";
import { acceptFrame, closed, START, type Stream } from "./liveState";
import { paths, socketUrl } from "./liveApi";

/**
 * Events over /ws/live (the user's shell, dense) or /ws/rep (the rep page,
 * server-filtered). A reconnect is the user's click and resumes at the last
 * seq + 1; nothing reconnects or retries on its own.
 */
export function useEventStream(kind: "live" | "rep", id: string) {
  const [stream, setStream] = useState<Stream>(START);
  const [attempt, setAttempt] = useState(0);
  const current = useRef<Stream>(START);

  useEffect(() => {
    let mine = true;
    const set = (s: Stream) => {
      current.current = s;
      setStream(s);
    };
    const path = kind === "live" ? paths.liveSocket : paths.repSocket;
    const ws = new WebSocket(socketUrl(path(id, current.current.next)));
    ws.onopen = () => mine && set({ ...current.current, phase: "open", message: "" });
    ws.onmessage = (m: MessageEvent) => {
      if (!mine) return;
      const next = acceptFrame(current.current, String(m.data), kind === "live");
      set(next);
      if (next.phase === "error") ws.close();
    };
    ws.onclose = (c) => mine && set(closed(current.current, c.code, c.reason));
    return () => {
      mine = false;
      ws.close();
    };
  }, [kind, id, attempt]);

  const reconnect = () => {
    current.current = { ...current.current, phase: "connecting", message: "" };
    setStream(current.current);
    setAttempt((a) => a + 1);
  };
  return { stream, reconnect };
}
