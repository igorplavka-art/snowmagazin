# Snowmagazin recovery instructions

## Goal
Recover and reconstruct all historical NextGEN galleries from Snowmagazin. Work gallery-by-gallery or in independent parallel batches.

## Durable storage rule
Every durable result created for this project must exist in both places:
1. GitHub repository `igorplavka-art/snowmagazin` (manifests, inventories, evidence, recovery code/workflows).
2. Google Drive project `SNOWMAGAZIN`, NextGEN root folder ID `1BLvM8IB4s3DXbjKYg-8MMQbbBg9tsbqH` (original recovered media plus mirrored durable project outputs).

Never leave unique recovered data only in GitHub Actions artifacts. Artifacts are transport/staging only.

## Reference gallery
`racibor` (NextGEN ID 66) is complete: 12/12 originals verified with hashes and mirrored to Drive. Do not re-recover it unless performing an audit.

## Parallel-agent split
Independent galleries may be processed by separate agents/worktrees. Prefer one gallery or a small non-overlapping gallery batch per agent. The orchestrator owns `nextgen_galerie/inventory.csv` and integration to avoid merge conflicts.

Suggested roles:
- discovery: gallery IDs, folders, article links, archived URL evidence;
- recovery: Wayback/live-original retrieval;
- reconstruction: manifest and article/gallery linkage;
- QA/mirror: image validation, SHA-256, count, duplicate check, Drive upload verification.

## Completion gate
A gallery may be marked `complete` only when:
- expected image set is supported by evidence;
- recovered media opens as valid images;
- each recovered file has byte size and SHA-256 in its manifest;
- originals are stored in the Drive NextGEN root under a gallery subfolder;
- Git contains the durable manifest/evidence;
- Git and Drive counts/hashes have been checked.

If completeness cannot be proven, use `partial`/`candidate` and state exactly what is missing. Never invent gallery IDs, filenames, counts, URLs, dates or mappings.

## Current durable discovery source
See `nextgen_galerie/_recovery_sources/` and `nextgen_galerie/inventory.csv`.
