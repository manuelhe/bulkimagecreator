# 03: Variation Phase Batch Traversal, WebP Encoding, and Live Progress

**What to build:**
Following seed image acceptance (or when supplied with `--prompts-file`), the tool traverses variation prompts using exclusively `00_seed.png` as the visual ancestor (ADR 0001). It formats each prompt with `--prompt-template` (defaulting to `"{prompt}"`), calls the image generation service, converts and saves each successful variation in WebP format (ADR 0002) with sequential numbering (`01_variation.webp`, `02_variation.webp`), updates `run_manifest.json` in real time, displays a live Rich progress bar, and prints a final execution summary table upon completion.

**Blocked by:** 02: Interactive Seed Phase Loop, Candidate Review, and Seed Image Promotion (#3)

**Status:** completed

- [x] Reads variation prompts from file via `--prompts-file` or prompts interactively when omitted
- [x] Applies template formatting (`--prompt-template`, e.g. `"{prompt}"`) to each raw variation prompt
- [x] Passes exclusively `00_seed.png` and the formatted variation prompt as multimodal input to the model (ADR 0001)
- [x] Saves all variation images in WebP format with zero-padded sequential numbers (`01_variation.webp`, `02_variation.webp`) (ADR 0002)
- [x] Displays real-time progress using Rich progress bar (showing current prompt index, total, successes)
- [x] Appends each variation result atomically to `run_manifest.json`
- [x] Displays a terminal summary table upon completion with total prompts, successful images, and output directory path
- [x] Test suite verifies batch traversal, template expansion, sequential naming, WebP encoding, and manifest synchronization
