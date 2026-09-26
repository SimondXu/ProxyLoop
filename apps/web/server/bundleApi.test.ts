import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { route, runs } from "./bundleApi";

const fixtures = fileURLToPath(new URL("../../../tests/web/fixtures", import.meta.url));
const [runId = "", dir = ""] = [...runs(fixtures)][0] ?? [];
const get = (url: string, root = fixtures) => route(root, "GET", url);

describe("bundleApi", () => {
  it("lists the fixture with its task", () => {
    const reply = get("/api/bundles");
    expect(reply?.status).toBe(200);
    expect(JSON.parse(reply?.body ?? "")).toEqual({
      bundles: [{ run_id: runId, root: "fixtures", complete: true, task_ref: "cp-direct-discount@1" }],
    });
  });

  it("serves one bundle directory as a root of one run", () => {
    const listed = JSON.parse(get("/api/bundles", dir)?.body ?? "") as { bundles: { run_id: string; root: string }[] };
    expect(listed.bundles.map((b) => [b.run_id, b.root])).toEqual([[runId, "fixtures"]]);
    expect(get(`/api/replay/${runId}/events`, dir)?.status).toBe(200);
  });

  it("serves the three files and one prompt by sha", () => {
    expect(get(`/api/replay/${runId}/manifest`)?.type).toBe("application/json");
    const events = get(`/api/replay/${runId}/events`);
    expect(events?.type).toBe("application/x-ndjson");
    const prompts = get(`/api/replay/${runId}/prompts`)?.body ?? "";
    const first = JSON.parse(prompts.split("\n")[0] ?? "") as { sha: string };
    const one = get(`/api/replay/${runId}/prompts/${first.sha}`);
    expect(JSON.parse(one?.body ?? "")).toMatchObject({ sha: first.sha });
    expect(get(`/api/replay/${runId}/prompts/${"0".repeat(64)}`)?.status).toBe(404);
  });

  it("never escapes the bundle root", () => {
    const escapes = [
      "/api/replay/../manifest",
      "/api/replay/..%2F..%2Ftests%2Fweb%2Ffixtures/manifest",
      "/api/replay/%2E%2E/events",
      `/api/replay/${runId}/..%2F..%2FAGENTS.md`,
      `/api/replay/${runId}/prompts/..%2Fmanifest.json`,
      `/api/replay/${runId}/manifest/extra`,
      `/api/replay/${runId}/events/${"a".repeat(64)}`,
      "/api/replay/%E0%A4%A/manifest",
      "/api/replay/unknown-run/manifest",
    ];
    for (const url of escapes) expect([url, get(url)?.status]).toEqual([url, 404]);
    expect(route(fixtures, "POST", "/api/bundles")?.status).toBe(405);
    expect(get("/index.html")).toBeNull();
  });

  it("redacts URLs like the real API, and 404s a missing prompts file", () => {
    const root = mkdtempSync(join(tmpdir(), "pl-web-"));
    mkdirSync(join(root, "r1"));
    writeFileSync(join(root, "r1", "manifest.json"), '{"endpoint":"https://relay.example/v1"}');
    writeFileSync(join(root, "r1", "events.jsonl"), "");
    expect(get("/api/replay/r1/manifest", root)?.body).toBe('{"endpoint":"<redacted-url>"}');
    expect(get("/api/replay/r1/prompts", root)?.status).toBe(404);
    const listed = JSON.parse(get("/api/bundles", root)?.body ?? "") as { bundles: unknown[] };
    expect(listed.bundles).toEqual([{ run_id: "r1", root: root.split("/").pop(), complete: true, task_ref: null }]);
  });
});
