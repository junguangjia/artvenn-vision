# Result format

`input.json` is a private local manifest. It stores each source path and SHA-256,
the derived preview path and SHA-256, processing dimensions, window membership,
and the user's `same_object` declaration. Source paths and EXIF are not passed
into the model prompt. Only opaque image IDs and derived RGB previews are passed.

`result.json` uses `schema_version: "artvenn-vision-result-v1"` and includes:

- `status`: `completed`, `partial`, or `failed`.
- `human_review_required`, always true; `cloud` and `mock`, always false.
- `binding`: the input, model profile, prompt version and generation settings hash.
- `model`: exact model ID, revision, weight and configuration/template hashes.
- `segments`: original per-window proposals, timings and failure categories.
- `grouping`: effective user-declared grouping or AI candidate groups.
- `attempt`: the latest worker's load time and memory measurements when available.
- `attempt_seconds`: the latest attempt's wall time, including local validation.
- `reused_segments`: successful windows reused by the latest invocation.

An example proposal for one synthetic image is:

```json
{
  "groups": [{"key": "g1", "asset_ids": ["a0001"], "fields": []}],
  "roles": [{"asset_id": "a0001", "role": "overview", "evidence": ["a0001"]}],
  "relationships": [],
  "issues": []
}
```

All four arrays are required. Every photo must occur in exactly one group and
have exactly one role. Group fields require evidence from that group. A field
value is a string, preserving literal source language and uncertain attributions.
No approval, publication, confidence or historical-truth fields are accepted.

When `same_object` is true, the effective object includes all prepared images,
including images in failed windows. That declaration does not fabricate missing
roles or fields. Consult each window's status before using any recognition result.
When false, group keys are qualified by window ID and cross-window identity remains
unresolved. Relationships refer to the window's original group keys.

The strict Python validator is the canonical proposal contract. Raw generated
text is retained in private `attempt-*.raw.txt` files for local diagnosis; it is
never treated as trusted output or printed by the CLI.
