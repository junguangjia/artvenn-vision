# Model configuration

The bundled profile freezes the original Qwen3-VL-4B-Instruct MLX 4-bit model.
`analyze` verifies weight and tokenizer/configuration/template filenames, sizes
and hashes, model family and quantization before loading them or reusing a run,
with `trust_remote_code=False` and
`local_files_only=True`. Configurations declaring custom `model_file` Python code
are refused because MLX-VLM 0.7.4 loads that code even when remote-code trust is
disabled. This extraction keeps the original runtime versions.

To compare a locally downloaded Qwen3-VL-8B-Instruct MLX 4-bit model, first select
an exact 40-character upstream commit and obtain the artifacts from that revision.
Then record the local weights:

```sh
uv run artvenn-vision register-model \
  --model-dir /path/to/qwen3-vl-8b \
  --model-id mlx-community/Qwen3-VL-8B-Instruct-4bit \
  --revision YOUR_EXACT_40_CHARACTER_COMMIT_SHA \
  --output /path/to/qwen3-vl-8b-profile.json

uv run artvenn-vision analyze \
  --run runs/separate-8b-comparison \
  --model-dir /path/to/qwen3-vl-8b \
  --profile /path/to/qwen3-vl-8b-profile.json
```

Prepare a separate run for the comparison. Resuming a 4B run with an 8B profile
is rejected. Registration records the bytes and provenance you supply; it does
not authenticate the claimed upstream revision or establish recognition quality.
It supports single or sharded `.safetensors` weights for Qwen3-VL 4-bit models.
Other model families and quantization formats are outside the extraction scope.

For a fair comparison, use the same photos, preview recipe, batch size and token
limit. Measure complete-run time, GPU memory, invalid-output rate, grouping errors,
role errors and exact-text accuracy against human annotations. A larger model
fitting into memory does not alone establish that it is best for the project.

The upstream model is separate from this package. Consult its model card and
license before redistribution:

- [Qwen3-VL-4B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct)
- [Pinned MLX conversion](https://huggingface.co/mlx-community/Qwen3-VL-4B-Instruct-4bit/tree/2fd8dacbdb8f1e54b8c005f081ec5bf79c56376b)
- [MLX-VLM](https://github.com/Blaizzy/mlx-vlm)
