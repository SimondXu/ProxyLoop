# Versioned data metadata

Only manifests, schemas, and redacted fixtures may be committed. Raw customer data, model weights, audio, and generated training corpora stay outside Git.

Phase 02 commits the normalized trajectory JSON Schema, accepted/quarantine metadata manifests, an aggregate cost/quality report, and a small redacted sample prepared for human review. The complete 128-record normalized pilot is reproducible through `make data-pilot` but is not committed as a training dataset.
