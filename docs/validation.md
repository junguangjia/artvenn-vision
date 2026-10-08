# Validation

Automated validation covers strict proposal acceptance, malformed/untrusted output,
image preparation and source preservation, explicit grouping across inference
windows, model profiles, checkpoint binding, resume and process failure handling.
CI requires formatting, lint, type checking, tests and a wheel/source build.

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
