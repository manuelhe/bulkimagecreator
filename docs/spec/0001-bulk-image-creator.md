# Specification: Bulk Image Creator CLI

## Problem Statement

Content creators, game designers, and digital artists frequently need to generate dozens or hundreds of image variations derived from a specific visual concept. Using web-based chat interfaces to upload multiple reference photos, refine a base image through trial and error, and then manually submit dozens of individual variation prompts is tedious, error-prone, and slow. Furthermore, transient API failures or safety filter triggers during batch generation often halt entire scripts, causing wasted compute, broken numbering, and lost outputs.

## Solution

A resilient, command-line application that automates the transition from multi-image reference curation to high-volume image variation generation. The user inputs 1 to 4 reference source images and enters an interactive seed phase to iteratively generate and review candidate images until satisfied. Once accepted as the seed image, the tool executes an automated variation phase, traversing a catalog of variation prompts using only the seed image as the visual reference. Non-recoverable failures (such as safety blocks) are logged and skipped to maximize total yield, while transient errors are retried with exponential backoff. All source images, candidate iterations, seed images, and variations are preserved in self-contained, numbered run folders with structured execution manifests.

## User Stories

1. As a creator, I want to pass 1 to 4 source image paths as command-line arguments, so that the model has multi-image visual references for the initial generation.
2. As a creator, I want the CLI to validate that my source images exist and are valid image formats before making API calls, so that I receive immediate feedback on bad paths.
3. As a creator, I want the CLI to reject execution if zero or more than 4 source images are provided, so that I comply with model input limits.
4. As a creator, I want to specify an initial seed prompt via a `--prompt` CLI flag, so that I can initiate generation directly from a script.
5. As a creator, I want the CLI to interactively prompt me for a seed prompt if I did not pass one as a flag, so that I don't have to remember all arguments up front.
6. As a creator, I want each run to be stored in an isolated, timestamped run directory, so that separate generation sessions never overwrite each other.
7. As an archivist, I want the tool to copy my 1 to 4 source images into a `sources/` subfolder inside the run directory, so that the run remains self-contained and reproducible even if the original source files move or get deleted.
8. As a creator, I want the tool to save candidate images in a `candidates/` folder with zero-padded numbers (`candidate_01.png`), so that none of my generated trials are lost.
9. As a macOS user, I want each generated candidate image to open automatically in my system viewer, so that I can immediately inspect the visual quality without navigating folders.
10. As a power user, I want a `--no-open` flag to disable automatically launching the image viewer, so that unattended or remote terminal sessions run cleanly.
11. As a creator, I want an interactive terminal menu after each candidate image generation that lets me accept the candidate, retry with the same prompt, edit the prompt, or quit, so that I remain in full control of the curation process.
12. As a creator, I want to retry candidate generation with the same seed prompt, so that I can explore non-deterministic model variations of the same idea.
13. As a creator, I want to edit my seed prompt during the seed phase without restarting the CLI, so that I can iteratively refine the composition.
14. As a creator, I want the ability to pick any previously generated candidate image by its number, so that I can select an earlier favorite after subsequent experiments fail to improve on it.
15. As a creator, I want candidate images and the accepted seed image saved in lossless PNG format, so that visual fidelity is preserved when used as an ancestor for variations.
16. As a creator, I want the chosen candidate copied to `00_seed.png` in the run directory root, so that the foundation for subsequent variations is clearly identifiable.
17. As a batch processor, I want to supply a variation prompts file via `--prompts-file`, so that I can run batch generations from predefined text lists.
18. As an interactive user, I want the CLI to prompt me for variation prompts if `--prompts-file` is omitted, so that I can provide prompt paths or input interactively.
19. As a prompt engineer, I want an optional `--prompt-template` flag (e.g. `"Transform this image to: {prompt}"`), so that I can reuse concise modifier lists across different creative styles.
20. As a user, I want each variation call in the variation phase to send only the accepted seed image and the variation prompt to the model, so that visual style remains consistent without prompt conflict from raw reference images.
21. As a user, I want to configure an optional `--aspect-ratio` flag with choices `1:1`, `3:4`, `4:3`, `9:16`, and `16:9` (defaulting to `1:1`), so that outputs match my target layout.
22. As a storage-conscious creator, I want generated variations saved in WebP format, so that hundreds of outputs consume minimal disk space and are ready for web distribution.
23. As an organizer, I want variation outputs sequentially numbered (`01_variation.webp`, `02_variation.webp`), so that files sort chronologically in file explorers.
24. As a batch processor, I want the tool to automatically retry transient errors (such as HTTP 429 rate limits or network drops) with exponential backoff, so that temporary spikes do not break my batch.
25. As a batch processor, I want the tool to immediately skip non-transient errors (such as safety filter triggers or model rejections) and continue to the next prompt, so that the batch yields the maximum possible number of successful images.
26. As a user, I want an inter-request delay configured via `--delay` (defaulting to 1.5 seconds), so that I avoid exceeding API rate limits during bulk generation.
27. As a supervisor, I want a live Rich progress bar showing current prompt progress, success counts, and skipped counts during the variation phase, so that I can monitor progress at a glance.
28. As an auditor, I want a `run_manifest.json` file written to the run directory that records run parameters, source paths, candidate history, prompt mappings, output filenames, and detailed failure reasons for skipped prompts, so that I have a complete machine-readable audit trail.
29. As a user, I want `run_manifest.json` updated incrementally after each variation is processed, so that progress is captured even if the CLI process is killed unexpectedly.
30. As a user, I want to resume an interrupted batch using `bulkimagecreator resume <run_dir>`, so that I can complete unfinished or skipped prompts without re-running the seed phase.
31. As a user, I want a summary table printed to the terminal upon batch completion displaying total prompts, successful images, skipped prompts, and the output directory location, so that I get a clear final status report.
32. As a developer, I want API authentication handled via the `GEMINI_API_KEY` environment variable or a local `.env` file, so that secrets are not hardcoded or checked into version control.

## Implementation Decisions

- **Domain Model Adherence**: All code, structures, variables, and documentation must adhere strictly to the terms defined in `CONTEXT.md` (`Source Image`, `Seed Prompt`, `Candidate Image`, `Seed Image`, `Seed Phase`, `Prompt Template`, `Variation Prompt`, `Variation Phase`, `Run`, `Run Manifest`).
- **Architectural Seam**:
  The application is structured into three primary architectural boundaries:
  1. CLI & Presentation: Handles command-line arguments, options, terminal rendering, interactive menus, progress displays, and OS viewer launching.
  2. Orchestration & State Machine: Governs the transitions of the Seed Phase and Variation Phase, directory management, image format conversion (PNG vs WebP), and atomic updates to the Run Manifest.
  3. Image Generation Service: A single boundary abstraction responsible for constructing multimodal payloads (multimodal prompt + image buffers) and calling the Gemini Nano Banana image generation model via the `google-genai` SDK.
- **Image Lineage**: In accordance with ADR 0001, the Variation Phase exclusively supplies the `Seed Image` as the visual context to the model, omitting the original source images to preserve stylistic continuity and optimize multimodal token usage.
- **Dual Format Encoding**: In accordance with ADR 0002, candidate and seed images are encoded as lossless PNG, while all variation images are converted and encoded as WebP before writing to disk.
- **Resilience & Fault Policy**:
  - Transient failures (HTTP 429 Too Many Requests, HTTP 503 Service Unavailable, network connection timeouts) trigger up to 2 retries using exponential backoff (e.g. 2s, 4s).
  - Permanent failures (Safety rating blocks, prompt recitation blocks, invalid argument errors) are marked as `skipped` in the Run Manifest along with the specific diagnostic reason, and traversal immediately proceeds to the subsequent variation prompt.
- **Run Manifest Schema**:
  The `run_manifest.json` schema documents:
  - `run_id`: Unique timestamped identifier (e.g., `run_20260921_173000`).
  - `status`: Lifecycle state (`in_progress`, `completed`, `interrupted`).
  - `config`: Target model, aspect ratio, prompt template, inter-request delay.
  - `sources`: List of archived source image records with original paths and relative run paths.
  - `seed_phase`: List of all generated candidate iterations, the accepted candidate identifier, and the final seed prompt.
  - `variations`: Array of items containing sequence index, input prompt, expanded prompt, execution status (`success` or `skipped`), output filename (if successful), and error diagnostic (if skipped).
- **Interruption Recovery**: The resume command loads `run_manifest.json`, identifies variation items that are pending or were skipped due to transient errors, verifies the existence of `00_seed.png`, and continues traversal.

## Testing Decisions

- **Testing Philosophy**: Tests must exercise user-observable behavior and public command workflows rather than asserting on internal implementation details.
- **Test Seam**:
  The test suite will inject a mock/stub at the `ImageGenerationService` boundary. This single seam allows the entire CLI pipeline—including argument parsing, source file validation, directory archiving, interactive seed phase menus, candidate selection, seed promotion, template expansion, WebP conversion, rate-limit backoff, safety skip handling, manifest serialization, and resume workflows—to run in complete end-to-end integration without network calls or incurring API costs.
- **Key Test Scenarios**:
  1. Source image validation (rejecting 0 or >4 images, rejecting non-existent paths).
  2. Seed phase interaction (retrying with same prompt, editing prompt, selecting prior candidate #, promoting to `00_seed.png`).
  3. Variation phase batch execution (template formatting, sequential numbering, WebP encoding).
  4. Failure handling (recovering from a 429 response via backoff, skipping a safety-blocked prompt, continuing the batch).
  5. Run manifest verification (verifying structured JSON state after partial and full runs).
  6. Batch resumption (verifying `resume` picks up only unprocessed items and preserves existing variations).

## Out of Scope

- Real-time video generation or animated GIF output.
- Cloud storage synchronization (e.g., uploading to S3 or Google Cloud Storage).
- Inpainting or pixel-level mask drawing UI.
- Web or graphical user interface (the tool is strictly a command-line application).
- Multi-threaded or distributed parallel API generation (requests are sequenced with deliberate pacing delay to avoid quota exhaustion).

## Further Notes

- API keys are passed via `GEMINI_API_KEY` in environment or `.env` files.
- Default image generation model is set to `gemini-3.1-flash-lite-image`, overridable via `--model`.
