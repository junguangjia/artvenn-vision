# Extraction provenance and scope

Source project: ArtVenn / `moya-inscriptions-web`.
Source commit: `38fe82c20b66bc48a645a2e60853b741cb67608c`.

| Source component | Standalone component | Adaptation |
| --- | --- | --- |
| `scripts/curation/proposal_schema.py` | `schema.py` | Strict evidence contract, English prompt, duplicate JSON key rejection |
| `scripts/curation/model_runner.py` | `engine.py`, `worker.py` | Offline inference, private checkpoints, timeouts, configurable pinned model profile |
| Preview preparation in `registry.py` | `images.py` | Selected-folder preparation without SQLite or review-system dependencies |
| `raw_decoder.py` | Optional RAW preparation in `images.py` | LibRaw preview recipe without the registry or Label Studio environment |
| `runtime-metadata.json` | Bundled model profile | Preserved 4B revision, weights hash and runtime version pins |
| Worker orchestration | `pipeline.py`, `cli.py` | Standalone subprocess, resume binding and explicit same-object declaration |

No source files were moved or removed from the original project. Its runtime,
review data, application and website behavior remain separate. Future adoption
by ArtVenn would be a separate integration change.

Excluded: website/backend/CMS code, publishing adapters, server database schema,
credentials, private configuration, originals, preview datasets, model weights,
Label Studio, native app shell and existing private human review history.

## Professional annotation adaptation

The professional image taxonomy and algorithm extension contracts were adapted
from the source application's `scripts/curation/photo_annotations.py` and its
versioned annotation schemas. The independent package uses its own additive local
SQLite review store and English loopback editor. It has no dependency on the
source registry, Label Studio, CMS or protected runtime configuration.

The local store freezes source image hashes, input identity and completed AI
proposals; arbitrary group/single human assignments are separate revisions.
Existing source application data was not moved or imported into the public
repository. Region drawing, actual model results and website integration require
separate implementations against the reserved contracts.

The source application's Apache-2.0 license is retained in `LICENSE`. No source
photographs or research datasets are included. Third-party packages and model
artifacts retain their own licenses and are not bundled into the source repository.
