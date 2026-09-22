"""Phase 03C Stage 2 (local MLX LoRA variant) training pipeline.

The contract's Stage 2 recipe (TRL + PEFT on a cloud GPU) runs here as
``mlx_lm.lora`` on the local Apple silicon machine because no cloud GPU
credential exists; every run manifest records that deviation.  This package
prepares the chat-format dataset from accepted teacher rows, renders the
``mlx_lm.lora`` YAML config, evaluates adapters on the development rows with
the real Phase 03C evaluator, and builds the committed run manifest.  Nothing
here loads a model except through the injected seams of the scripts.
"""
