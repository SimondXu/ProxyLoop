# Third-party sources

No third-party code is vendored in this repository. `scripts/sys/fetch_external.sh` clones each pinned
repository into `external/` (git-ignored; override with `EXTERNAL_DIR=<dir>`), checks out the pinned
commit and fails unless `HEAD` equals the pin and the checkout is clean. Re-running it is safe.

| Name | Upstream | Pinned commit | Commit date | Licence | Use here |
|---|---|---|---|---|---|
| TalkAct (VoiceComputerBench) | https://github.com/19PINE-AI/TalkAct | `7d70007f72d45ddfc1a14e8e229b6d444e4919a2` | 2026-07-19 | MIT, © 2026 19PINE-AI | anchor rows reproduced in TalkAct's own harness (EVAL.md) |
| principal-loyalty (PrincipalBench) | https://github.com/19PINE-AI/principal-loyalty | `776e92137acc784f3088ab94587c6c13afed488c` | 2026-07-29 | MIT, © 2026 Bojie Li, Noah Shi, and Pine AI | diagnostic subset only (EVAL.md) |

Rules (NORTH_STAR I9): neither source is ever trained on, and that includes the SFT/DPO data shipped in
principal-loyalty's `data/`. Results computed on them are labelled as our reproduction or a diagnostic
subset. Each licence text is the `LICENSE` file at the pinned commit; keep its notice with any excerpt.
