// Phase 07 D2: where the Web's `/api/runtime/*` rewrite sends requests.
// `next.config.ts` reads PROXYLOOP_RUNTIME_ORIGIN; the rewrite destination is
// fixed when `next build` writes the routes manifest, and `next start` only
// re-validates the value when it loads the config. The demo launcher always
// sets it from its Runtime port. Only a loopback `http://host:port` origin on
// 127.0.0.1 or localhost is accepted; anything else throws so the build fails
// closed. A bracketed IPv6 host is refused because Next's rewrite compiler
// cannot parse it at request time.

export const DEFAULT_RUNTIME_ORIGIN = "http://127.0.0.1:8000";

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost"]);

export function runtimeOrigin(value: string | undefined): string {
  if (value === undefined || value.trim() === "") return DEFAULT_RUNTIME_ORIGIN;
  const refuse = (): never => {
    throw new Error(
      "PROXYLOOP_RUNTIME_ORIGIN must be a loopback http://host:port origin " +
        "(127.0.0.1 or localhost) with no path, query, or credentials.",
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
