// Phase 07 D2: where the Web's `/api/runtime/*` rewrite sends requests.
// `next.config.ts` reads PROXYLOOP_RUNTIME_ORIGIN at build and start; the
// demo launcher always sets it from its Runtime port. Only a loopback
// `http://host:port` origin is accepted; anything else throws so the build
// fails closed instead of proxying to another host.

export const DEFAULT_RUNTIME_ORIGIN = "http://127.0.0.1:8000";

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);

export function runtimeOrigin(value: string | undefined): string {
  if (value === undefined || value.trim() === "") return DEFAULT_RUNTIME_ORIGIN;
  const refuse = (): never => {
    throw new Error(
      "PROXYLOOP_RUNTIME_ORIGIN must be a loopback http://host:port origin " +
        "(127.0.0.1, localhost, or [::1]) with no path, query, or credentials.",
    );
  };
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return refuse();
  }
  if (
    url.protocol !== "http:" ||
    !LOOPBACK_HOSTS.has(url.hostname) ||
    url.port === "" ||
    url.username !== "" ||
    url.password !== "" ||
    url.pathname !== "/" ||
    url.search !== "" ||
    url.hash !== "" ||
    value.includes("?") ||
    value.includes("#")
  ) {
    return refuse();
  }
  return url.origin;
}
