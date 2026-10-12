# Professional annotations and algorithm data

Start with a prepared run: `artvenn-vision prepare <folder> --output <new-run>`.
Analysis is optional for manual review. Start `artvenn-vision review --run <run>`
and open its printed loopback URL. All interface text is English; your titles and
visible source text retain their original language.

## Organize without rewriting AI groups

Select an AI source group, individual photos, or any combination. Assign the
selection to a named new or existing object. An overview, reverse, side and detail
can all belong to one inscription. The object title names the archive; original
filenames and image bytes do not change. AI proposals remain immutable evidence,
even when you decide to combine or split their assignments.

All prepared photos remain available, including unprocessed and failed AI windows.
Processing-window identity is never treated as physical object identity. A
single-object declaration is shown separately from AI grouping authority.

## Independent annotation dimensions

| Dimension | Values and meaning |
| --- | --- |
| Photo role | Overview, detail, label, context, unspecified |
| Object kind | Inscription, calligraphy, unknown |
| Representation | Original stone, original ink work, rubbing, facsimile, unknown |
| Capture method | Photograph, scan, unknown |
| Capture coverage | Whole object, whole surface/page, detail, context, label, unknown |
| Stele surfaces | Front, back, unspecified side, left, right, other, unknown, not applicable; multiple allowed |
| Side reference | Left/right are relative to facing the front; preserve unknown orientation |
| Stele parts | Head, body, base, other, unknown, not applicable; multiple allowed |
| Calligraphy format | Handscroll, album, folded book, hanging scroll, other, unknown, not applicable |
| Calligraphy positions | Main work, frontispiece, tail, cover/mount, leaf/page, other, unknown, not applicable; multiple allowed |
| Content | Main text, stele title, title, colophon, title slip, signature, seal, ornament, damage, label, unknown; multiple allowed |
| Version and order | Rubbing/version label, page or capture index |
| Evidence | Notes for uncertainty and the basis of a label |

The photo role describes a broad use; it does not replace surface, physical part,
content or representation. A rubbing is distinct from a photograph of the original
stone. A frontispiece position and a title text region are different concepts.
Left/right requires a known reference. Missing photographs do not prove that a
surface, colophon or seal does not exist.

Per-photo controls and the floating bulk toolbar edit the same fields. Bulk
operations distinguish no change, replace, add, remove and explicit clear.
Only the selected photos change. Keeping a field unknown or empty is preferable
to guessing; the UI does not force a complete set of professional labels.

## Save, explicitly confirm, then export

Save stores a new private revision. Confirmation requires a saved revision, a
reviewer name and a complete object assignment. The database keeps previous
revisions and confirmation records append-only. Confirmed records identify a
human decision; they do not certify OCR accuracy or historical truth. Subsequent
edits require another save and explicit confirmation. Optimistic revision checks
reject stale tabs instead of overwriting a newer decision.

An export contains `dataset.json`, `manifest.json`, contract schemas and checksum
records. Source image hashes and stable image IDs bind labels to the prepared run.
Current confirmed labels are separated from draft/history records. AI proposals,
source-group membership and human assignments remain distinguishable. Default
exports reject unconfirmed edits; the Python API can explicitly export an
unconfirmed dataset, marked as such, for inspection rather than training truth.
No original or preview images, local filesystem paths, runtime logs or credentials
are included in exported metadata. Exports are local files and never publish data.

Each exported asset has an `original_frame`: verified encoded pixel width/height
and EXIF orientation from the hash-verified Original, or an explicit unknown frame
when metadata cannot be read. Preview dimensions cannot substitute for this frame.
AI provenance includes the bound input, model identity/artifact hashes, prompt and
generation settings, or the verified import digest and synthetic marker.

## Reserved region and algorithm result interfaces

The bundled algorithm extension schema reserves region geometry, reading order,
uncertain transcription, registration and algorithm/model provenance. Region
geometry must identify the original image coordinate frame, source hash and
dimensions; rectangles and polygons require finite valid coordinates. Algorithm
results identify their input hashes, model/version and producing run. A candidate
result is separate from human confirmation.

The schema and validator are integration boundaries. This release does not provide
region drawing, character segmentation, OCR execution, image alignment, 3D
reconstruction or model training. Future integrations must preserve the original
image coordinate frame and immutable review lineage and record their own inputs,
uncertainty and validation. These annotations prepare inputs and evaluation data;
they do not automatically run or train an algorithm.
