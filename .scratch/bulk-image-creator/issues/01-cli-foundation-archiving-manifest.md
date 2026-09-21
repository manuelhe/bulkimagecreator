# 01: CLI Foundation, Source Image Archiving, and Run Manifest Tracer Bullet

**What to build:**
A user runs `bulkimagecreator run <source_images...>` providing 1 to 4 source image paths. The CLI validates argument boundaries (rejecting 0 or more than 4 images, verifying that files exist and are readable images), initializes an isolated timestamped directory (`runs/run_YYYYMMDD_HHMMSS/`), copies the source images into `sources/` for self-contained archiving, writes the initial `run_manifest.json` documenting the run configuration, and prints the run summary to the terminal.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Command fails with user-friendly error message if fewer than 1 or more than 4 source image paths are provided
- [ ] Command fails with a clear error message if any specified source image path does not exist on disk
- [ ] Automatically generates a timestamped run directory under `runs/` (or custom `--output-dir`)
- [ ] Copies all provided source images into `<run_dir>/sources/` preserving integrity
- [ ] Generates an initial `run_manifest.json` containing run metadata, timestamp, source paths, and status `in_progress`
- [ ] Test suite verifies argument validation, source archiving, and initial manifest generation
