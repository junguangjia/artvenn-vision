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

Excluded: website/backend/CMS code, publishing adapters, database schema,
credentials, private configuration, originals, preview datasets, model weights,
Label Studio, native app shell and human review history.

The source application's Apache-2.0 license is retained in `LICENSE`. No source
photographs or research datasets are included. Third-party packages and model
artifacts retain their own licenses and are not bundled into the source repository.
