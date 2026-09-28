// The replay library (`/`, redesign §3.4): one link per bundle /api/bundles lists,
// newest first as the API sends them. A row shows the task's family name made
// readable (the same as the start page's; titles wait for P1), the ref verbatim,
// the date in the run id and two chips: Evidence and Incomplete. No outcome chip
// until /api/bundles sends one (P2).
import { useEffect, useState } from "react";
import { listBundles, type BundleInfo } from "../bundleSource";
import { taskName } from "../start";
import { Banner } from "../ui/Banner";
import { Chip } from "../ui/Chip";
import { EmptyState } from "../ui/EmptyState";
import { isEvidence, runDate, runHref } from "./marks";
import "./replay.css";

export function ReplayLibrary() {
  const [bundles, setBundles] = useState<BundleInfo[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    listBundles()
      .then(setBundles)
      .catch((e: unknown) => setError(String(e)));
  }, []);
  return (
    <section className="pl-library">
      <h1>Recorded runs</h1>
      {error && (
        <Banner tone="danger" role="alert">
          {error}
        </Banner>
      )}
      {bundles?.length === 0 && <EmptyState title="No recorded runs yet." />}
      {bundles && bundles.length > 0 && (
        <ul className="pl-runs" aria-label="Recorded runs">
          {bundles.map((b) => {
            const date = runDate(b.run_id);
            return (
              <li key={b.run_id}>
                <a className="pl-run" href={runHref(location.search, b.run_id)}>
                  <span className="pl-run-title">{b.task_ref ? taskName(b.task_ref) : "Unknown task"}</span>
                  <span className="meta">{[b.task_ref, date].filter(Boolean).join(" · ")}</span>
                  <span className="pl-run-id">{b.run_id}</span>
                  <span className="pl-run-chips">
                    {isEvidence(b.root) && <Chip tone="guard">Evidence</Chip>}
                    {!b.complete && <Chip tone="attn">Incomplete</Chip>}
                  </span>
                </a>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
