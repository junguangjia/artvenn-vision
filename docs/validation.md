# Validation

Automated validation covers strict proposal acceptance, malformed/untrusted output,
image preparation and source preservation, explicit grouping across inference
windows, model profiles, checkpoint binding, resume and process failure handling.
CI requires formatting, lint, type checking, tests and a wheel/source build.

## Professional annotation verification, October 12, 2026

Ruff lint and formatting, mypy over all 14 source modules, 91 Python tests,
seven native JavaScript tests, and wheel/source builds passed locally. The wheel
contains all three editor assets and four contract schemas. Tests cover revision
conflicts, explicit confirmation, sparse bulk operations, malformed extension
geometry, result/source binding, export lineage and private loopback restrictions.
Preparation and worker-contract tests also accept 513 photos/windows without a
fixed total count cap while retaining at most eight photos per inference window.

An isolated prepared run used the Owner's 101 actual photographs and a hash-bound
import of their existing local AI proposals. All 18 source groups were preserved:
93 photos had AI proposals and eight remained honestly unprocessed but selectable.
No fresh model inference was performed for this review/export acceptance check.

The actual browser flow combined a source group with an individual photo, edited
purposes and multiple professional labels, saved and reopened a draft, assigned
all 101 photos to a named validation object, and explicitly confirmed a second
saved revision before exporting. The export retained 101 assets, 18 source groups,
three revisions including the initial draft, and one named confirmation. The
validation labels and reviewer were synthetic test decisions, not Owner-approved
historical annotations or a training dataset.

All 101 Original SHA-256 hashes matched preparation after the flow. Original image
bytes, existing application records and website Drafts were not written. Validation
artifacts stayed in a separate private local directory and are not included in Git.
At 390 and 1920 pixel viewport widths, the grid fit the viewport without horizontal
overflow and the selection toolbar remained visible near the end of the long page.

This validates standalone local review and metadata export. It does not establish
OCR quality, a new model comparison, region drawing, algorithm execution, installed
native-app deployment, cloud upload or public website publication.

## Local verification, October 7, 2026

On an Apple M5 Pro with 48 GB memory, a fresh standalone environment successfully
ran the pinned Qwen3-VL-4B-Instruct MLX 4-bit model on three generated synthetic
photos: a stone-shaped object, a label and a detail. Two inference windows (two
images, then one image) both returned valid proposals. The effective grouping
retained the user's single-object declaration across both windows.

| Measurement | Observed value |
| --- | --- |
| Worker attempt, including model validation and startup | 12.095 seconds |
| Model load | 0.644 seconds |
| Two-image inference window | 5.699 seconds |
| One-image inference window | 2.078 seconds |
| Peak MLX GPU memory | 4.018 GiB |
| Peak process RSS | 3.391 GiB |

The initial sandboxed attempt failed because Metal was unavailable in that
environment. The successful attempt ran locally with GPU access. This is an
installed-pipeline smoke check, not a performance guarantee. Synthetic fixtures
do not establish Chinese inscription OCR quality, 4B versus 8B ranking, or
performance on the owner's photos. RAW conversion retains an isolated 60-second
child deadline but still requires separate real RAW fixture acceptance.

Automated checks: 46 tests passed, including the independent review findings on
custom model code refusal, configuration hash binding, completed-checkpoint
authority, large-run resume and RAW timeout isolation. Formatting, lint, type
checks and wheel/source builds passed. Hosted CI results are recorded by GitHub
for each published commit.
