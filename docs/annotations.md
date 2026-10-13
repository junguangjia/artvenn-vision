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

## Direct image-label inspector

Select one photo with **Label this photo**, or combine whole groups and individual
photos. The same persistent inspector presents the useful image labels directly:

- **Carrier:** original stone, rubbing, original ink, facsimile, unknown.
- **Framing:** whole object, whole surface/page, detail, environment, exhibition label, unknown.
- **Location:** stele front/back/sides, or main work/frontispiece/tail/cover/page for calligraphy.
- **Visible content:** main text, stele title, colophon, title slip, signature and seal; positive multi-label tags.
- **Rubbing/version identifier:** optional when a relevant set is selected.

A partial tag click adds that tag to all selected photos; a unanimous tag click
removes it. Other tags remain unchanged. Scalar choices change only their own
field. **Apply to selected photos** puts staged patches into the draft. Selecting
a different set or changing its object assignment cancels unapplied patches with
a notice. Apply or discard before saving, confirming, exporting or reloading.
Changing the surface/location view only changes presentation. Left/right requires
explicit confirmation of the facing-front reference. Clearing a field means
unannotated; unknown and verified absence are different assertions. Unselected
content tags do not assert absence.

An explicit framing choice synchronizes the legacy broad photo role. Clearing
framing preserves that role, and existing AI roles never infer reviewed complete
surface/page coverage. Object assignment remains a separate human choice.

## Stored annotation dimensions and compatibility

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
| Version and order | Rubbing/version label; legacy image index, not verified reading order |
| Evidence | Notes for uncertainty and the basis of a label |

The photo role describes a broad use; it does not replace surface, physical part,
content or representation. A rubbing is distinct from a photograph of the original
stone. A frontispiece position and a title text region are different concepts.
Left/right requires a known reference. Missing photographs do not prove that a
surface, colophon or seal does not exist.

Acquisition method, mounting/format taxonomy, structural parts, image index and
long catalogue notes are omitted from the daily editor. Existing values are
retained in drafts, immutable revisions and exports; this UI change neither
migrates nor clears them. It does not force complete labels to save a draft.

## Why these fields, and what algorithms still need

This is a project design choice based on the tasks, not a universal mandatory
label set. DINOv2 extracts image and patch features without catalogue metadata.
LightGlue consumes keypoints/descriptors and returns correspondences. Surface
and framing tags help filter candidate image pairs, but cannot establish overlap
or geometric correctness. CalliReader uses manually labeled character boxes and
contents: a main-text tag does not replace region geometry or checked text.
[DINOv2 author repository](https://github.com/facebookresearch/dinov2),
[LightGlue author repository](https://github.com/cvg/LightGlue),
[CalliReader, section 5.2](https://arxiv.org/html/2503.06472v2).

Confirmed object identity, source hashes, Original pixel frames, separate AI
provenance and human revisions remain automatically available. Future OCR needs
text regions, checked transcription and explicit reading order; alignment needs
verified correspondences/transforms; seal detection needs individual seal
regions. The existing region/result extension contracts retain space for those
consumers. Routine image labels alone are not a complete supervised dataset.

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
