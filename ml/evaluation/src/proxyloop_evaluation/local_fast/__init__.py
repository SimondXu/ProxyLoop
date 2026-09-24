"""Local opt-in Fast backend: adapter conversion, gateway, and parity (PR-9b).

The Phase 03C distilled adapter is served by a separate loopback-only MLX
process that reuses the measured 03C code path (``Phase03CQwenAdapter`` with
the v6 prompt, greedy decoding, seed 0, thinking off).  Nothing here edits a
file bound by the r4 execution contract or the 03C smoke fingerprints; see
``harness/context/pr9-local-distilled-fast-design.md``.
"""
