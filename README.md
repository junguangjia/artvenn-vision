# ArtVenn Vision

Local image recognition for photographs of inscriptions and other cultural objects.
Extracted from ArtVenn's photo curation pipeline as an independent Python package.
All interfaces, prompts and documentation are English. Recognized source text stays
in its original language.

The model suggests photo groups, image roles, visible text and relationships, with
image IDs as evidence. Every result requires human review. Original photographs
remain unchanged. Inference uses MLX on Apple Silicon and has no cloud fallback.

## Quick start

Use Python 3.12 and [uv](https://docs.astral.sh/uv/). Model inference requires an
Apple Silicon Mac; preparation and automated tests also run on Linux.

```sh
git clone https://github.com/junguangjia/artvenn-vision.git
cd artvenn-vision
uv sync --locked --extra mlx

# One-time network download of the pinned public model; no photographs are sent.
uv run artvenn-vision download-model --model-dir models/qwen3-vl-4b

# Use --same-object when this folder contains photos of one known inscription.
uv run artvenn-vision prepare /path/to/inscription --output runs/inscription --same-object
uv run artvenn-vision analyze --run runs/inscription --model-dir models/qwen3-vl-4b
```

Read `runs/inscription/result.json`. The command prints only a small status summary;
recognized text, source paths, raw model output and runtime logs stay in the local
run directory. To use an existing model, pass its directory and skip the download.

JPEG, PNG, WebP and TIFF are supported. Optional Sony ARW, DNG, CR2 and NEF preparation
requires `uv sync --locked --extra mlx --extra raw`. RAW conversion uses LibRaw and
camera white balance; its preview colors are developed colors, not camera JPEGs.
Use `--recursive` to include selected subfolders. There is no fixed total photo or
group count cap. Inference still uses windows of at most eight images; per-file,
metadata-size and execution-time bounds remain. Larger runs require more local
storage, memory and processing time.

## Review, annotate and export

```sh
# Works before or after analysis, including partial runs. No model is loaded.
uv run artvenn-vision review --run runs/inscription
# Open the printed http://127.0.0.1:<port> URL in your browser.

# After an explicit human confirmation in the editor:
uv run artvenn-vision export --run runs/inscription --output datasets/inscription-v1
```

The English editor shows every prepared photo, including photos without a completed
AI result. AI source groups remain separate and unchanged. Select whole groups or
individual photos, assign them to a new or existing named object, and set image
roles and professional annotations individually or in batches. The toolbar stays
visible while scrolling and the grid adapts to the available window width.

Professional annotations distinguish stele surfaces and parts, calligraphy format
and position, content, representation, capture coverage and version. These are
independent of the broad photo role. A photo can contain multiple surfaces,
positions or content types. Unknown is a valid choice; do not manufacture labels.

**Save draft** stores an immutable revision without confirming it. **Confirm**
records your explicit decision and reviewer name for the saved revision. Editing
after confirmation creates another unconfirmed revision. Default exports require
the current revision to be confirmed and contain metadata, source hashes, AI
proposals and review history, with no original/preview image bytes or local paths.
See [annotation workflow and contracts](docs/annotations.md). Drawing regions and
running algorithms are reserved interfaces, not implemented analysis tools.

Starting a review freezes the prepared inputs and current AI result, including a
partial or absent result. Finish intended AI retries before starting durable review.
If analysis changes that result afterward, the existing review refuses reuse;
prepare a separate run and review while keeping the original records preserved.

## One folder, one inscription

`--same-object` records your explicit declaration that every selected photograph
belongs to the same physical object. `result.json` then contains one object under
`grouping.objects`, even when processing uses several windows of up to eight images.
The declaration is marked `authority: "user_declaration"`. AI proposals remain
separate under `segments`; conflicting fields and failed windows still need review.

Without this option, grouping is an AI suggestion within each window. Identity
across separate windows remains unresolved. A window number is never an object ID.
The package does not automatically merge similar objects or determine global
identity across a large collection.

## What the model returns

| Collection | Content |
| --- | --- |
| `groups` | Candidate objects and their supporting image IDs |
| `roles` | `overview`, `detail`, `label`, `context`, or `unspecified` per image |
| `fields` within each group | Visible `title`, `persons`, `period_original`, `object_form` |
| `relationships` | Same object, related objects, unrelated, or uncertain |
| `issues` | Unreadable text, conflicts, uncertainty and other review questions |

Fields retain literal source text and evidence IDs. Dates are not converted, and
unsupported historical facts are omitted. The schema rejects missing photos,
duplicate membership, invented evidence and approval fields. Schema validation
checks structure and references; it cannot establish OCR accuracy or historical truth.

## Models and costs

The reproducible baseline is `mlx-community/Qwen3-VL-4B-Instruct-4bit`, pinned to
revision `2fd8dacbdb8f1e54b8c005f081ec5bf79c56376b`. Its weights are approximately
3.09 GB and are verified by SHA-256 before inference. Runtime versions remain
the source pipeline's MLX-VLM 0.7.4 and MLX 0.32.3.

Qwen3-VL-8B-Instruct MLX 4-bit is a compatible candidate for a separate comparison.
It has **not** been benchmarked by this project's extraction validation. The
baseline is a reproducibility choice, not a claim that 4B offers the best recognition.
See [model configuration](docs/models.md) for using another pinned Qwen3-VL model.

Local inference consumes your Mac's memory, GPU time, storage and electricity.
It does not consume ChatGPT, Codex or a cloud API token allowance. Initial model
and package downloads require network access. Analysis sets the runtime's offline
flags and only loads local artifacts; this is an application boundary, not an OS
network sandbox.

## Resume and failures

Repeat the same `analyze` command to reuse completed windows and retry only failed
or unfinished ones. Changing source bytes, previews, prompt/model settings or
the model profile invalidates reuse. A completed run is returned without inference.
Preparation always requires a new output directory.

Malformed model output is rejected rather than silently repaired. A timeout or
cancellation preserves already completed windows. The exit code is `0` on success,
`2` for a partial or rejected operation, and `3` for an unexpected local failure.
The default overall inference timeout is 900 seconds; `--timeout`,
`--segment-timeout` and `--max-tokens` expose bounded controls. Each run has one
analysis lock. A stale lock after an abrupt parent-process crash requires checking
that no analysis process is running before manually removing that run's lock.

## Development

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
node --test tests/ui-review.test.mjs
uv build
```

GitHub CI runs formatting, lint, type checks, tests and package build without model
weights or a GPU. Actual MLX inference is a separate local check. See
[validation](docs/validation.md), [extraction provenance](docs/extraction.md) and
[the result format](docs/result-format.md).

Website publishing, CMS integration, Label Studio and the native app shell remain
in the original ArtVenn project. This package includes a private local review store
and browser editor and ends at recognition proposals and explicitly reviewed
metadata exports. Model weights and private photographs are not included in the
repository. Running this project never uploads photos or publicly publishes them.

