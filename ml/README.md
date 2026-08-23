# ML workspace

This independent environment contains Phase 02's CPU-only Data Factory and will later contain training, evaluation, and promoted-serving configuration behind separate human gates. Model weights, full generated datasets, and experiment artifacts are excluded from Git.

Phase 02 uses local path dependencies on the stable Safe Observation and fictional-Provider simulator interfaces. Runtime packages and services never import this workspace.

```text
uv run --project ml pytest -c ml/pyproject.toml -q
make data-pilot
make data-pilot-check
```

The current pilot makes no external model call and is not a training-ready corpus.
