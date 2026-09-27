// A read-only stand-in for the S1-SYS-09 replay API, served by the Vite dev and
// preview servers from one bundle root (PL_BUNDLE_DIR). Same five GETs, same
// shapes, so the web has one client path and switching to the real API is a
// base-URL/proxy change. Nothing here writes.
import { existsSync, lstatSync, readdirSync, readFileSync } from "node:fs";
import type { IncomingMessage, ServerResponse } from "node:http";
import { basename, dirname, join } from "node:path";
import type { Plugin } from "vite";

export type Reply = { status: number; type: string; body: string };

const FILES = { manifest: "manifest.json", events: "events.jsonl", prompts: "prompts.jsonl" };
const NDJSON = "application/x-ndjson";
const RUN_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*$/; // one path segment; never "." or ".."
const SHA = /^[0-9a-f]{16,128}$/;
const URLS = /https?:\/\/[^\s"'<>\\]+/g; // the real API redacts these too

const json = (status: number, value: unknown): Reply => ({
  status,
  type: "application/json",
  body: JSON.stringify(value),
});
const NOT_FOUND = json(404, { detail: "not found" });
// Symlinks are never followed (lstat): a link could point outside the root.
const isFile = (path: string) => existsSync(path) && lstatSync(path).isFile();
const isDir = (path: string) => existsSync(path) && lstatSync(path).isDirectory();

/** The runs under `root`, newest run_id first: `root` itself if it is one bundle. */
export function runs(root: string): Map<string, string> {
  const isRun = (dir: string) => isFile(join(dir, FILES.manifest)) || isFile(join(dir, FILES.events));
  if (isRun(root)) return new Map([[basename(root), root]]);
  if (!existsSync(root)) return new Map();
  const names = readdirSync(root).filter(
    (n) => RUN_ID.test(n) && isDir(join(root, n)) && isRun(join(root, n)),
  );
  return new Map(names.sort().reverse().map((n) => [n, join(root, n)]));
}

function listing(root: string): Reply {
  const found = runs(root);
  const label = basename(found.get(basename(root)) === root ? dirname(root) : root);
  const bundles = [...found].map(([run_id, dir]) => {
    const path = join(dir, FILES.manifest);
    const manifest = isFile(path)
      ? (JSON.parse(readFileSync(path, "utf-8")) as { task_ref?: string })
      : null;
    return { run_id, root: label, complete: manifest !== null, task_ref: manifest?.task_ref ?? null };
  });
  return json(200, { bundles });
}

/** Answer one request, or null when the path is not the API's. */
export function route(root: string, method: string, url: string): Reply | null {
  const path = url.split("?")[0] ?? "";
  if (!path.startsWith("/api/")) return null;
  if (method !== "GET" && method !== "HEAD") return json(405, { detail: "read-only" });
  let parts: string[];
  try {
    parts = path.split("/").slice(2).map(decodeURIComponent);
  } catch {
    return NOT_FOUND;
  }
  if (parts.length === 1 && parts[0] === "bundles") return listing(root);
  const [head, runId = "", file = "", sha, ...rest] = parts;
  const dir = head === "replay" && RUN_ID.test(runId) ? runs(root).get(runId) : undefined;
  if (dir === undefined || rest.length > 0 || !Object.hasOwn(FILES, file)) return NOT_FOUND;
  const name = join(dir, FILES[file as keyof typeof FILES]);
  if (!isFile(name)) return NOT_FOUND;
  const text = readFileSync(name, "utf-8").replace(URLS, "<redacted-url>");
  if (sha === undefined) {
    return { status: 200, type: file === "manifest" ? "application/json" : NDJSON, body: text };
  }
  if (file !== "prompts" || !SHA.test(sha)) return NOT_FOUND;
  const line = text
    .split("\n")
    .find((l) => l.trim() !== "" && (JSON.parse(l) as { sha?: string }).sha === sha);
  return line === undefined ? NOT_FOUND : { status: 200, type: "application/json", body: line };
}

export function bundleApi(root: string): Plugin {
  const handle = (req: IncomingMessage, res: ServerResponse, next: (err?: unknown) => void) => {
    let reply: Reply | null;
    try {
      reply = route(root, req.method ?? "GET", req.url ?? "/");
    } catch (err) {
      next(err);
      return;
    }
    if (reply === null) {
      next();
      return;
    }
    res.statusCode = reply.status;
    res.setHeader("Content-Type", reply.type);
    res.end(req.method === "HEAD" ? undefined : reply.body);
  };
  return {
    name: "pl-bundle-api",
    configureServer: (server) => void server.middlewares.use(handle),
    configurePreviewServer: (server) => void server.middlewares.use(handle),
  };
}
