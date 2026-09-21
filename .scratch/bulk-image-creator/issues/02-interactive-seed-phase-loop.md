# 02: Interactive Seed Phase Loop, Candidate Review, and Seed Image Promotion

**What to build:**
A user runs `bulkimagecreator run <source_images...> --prompt "..."` (or is prompted interactively if `--prompt` is omitted). The tool calls the multimodal image generation service passing the source images and seed prompt, saves each attempt as a lossless PNG under `candidates/candidate_NN.png`, automatically opens the OS image viewer on macOS (unless `--no-open` is specified), and presents an interactive terminal menu: `[a]ccept current | [p]ick candidate # | [e]dit prompt | [r]etry | [q]uit`. Upon acceptance, the chosen candidate is promoted to `00_seed.png` in the run root and logged in `run_manifest.json`.

**Blocked by:** 01: CLI Foundation, Source Image Archiving, and Run Manifest Tracer Bullet (#2)

**Status:** ready-for-agent

- [ ] Interactively prompts for seed prompt if `--prompt` is not supplied via CLI
- [ ] Generates candidate images using the multimodal image service seam and saves them as lossless PNGs (`candidate_01.png`, `candidate_02.png`, etc.)
- [ ] Automatically opens generated candidate image using system viewer (`open` on macOS), disabled when `--no-open` flag is passed
- [ ] Terminal menu provides choices: accept current candidate, pick any previous candidate by number, edit prompt, retry with same prompt, or quit
- [ ] Retrying or editing the prompt preserves previously generated candidates without overwriting
- [ ] Upon candidate acceptance, copies/promotes the selected candidate as `00_seed.png` in the run directory
- [ ] Updates `run_manifest.json` with seed prompt, all candidate iteration records, and the accepted candidate identifier
- [ ] Test suite verifies the interactive loop, candidate numbering, prompt modification, and seed promotion using mocked image generation seam
