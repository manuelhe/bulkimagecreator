# 05: Batch Interruption Recovery (resume CLI Command)

**What to build:**
A user runs `bulkimagecreator resume runs/<run_id>` on an interrupted or partially completed run. The command validates the run directory, verifies the existence of `00_seed.png`, inspects `run_manifest.json` to identify pending or skipped variation prompts, resumes generation using the existing seed image without repeating completed variations, and updates the manifest upon completion.

**Blocked by:** 04: Rate-Limit Pacing, Exponential Backoff, and Non-Transient Fault Skipping (#5)

**Status:** completed

- [x] `bulkimagecreator resume <run_dir>` validates directory existence, valid manifest JSON, and presence of `00_seed.png`
- [x] Inspects `run_manifest.json` to identify unprocessed and transiently failed variation prompts
- [x] Preserves all already generated variation images without overwriting or re-indexing them
- [x] Traverses remaining prompts with progress bar and pacing delay
- [x] Updates `run_manifest.json` status from `interrupted` to `completed` when all prompts are traversed
- [x] Test suite verifies resuming a partially completed run, ensuring only remaining prompts are executed
