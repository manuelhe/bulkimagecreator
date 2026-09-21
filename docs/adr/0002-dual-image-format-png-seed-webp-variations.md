# 0002. Dual Image Format Strategy: PNG for Seed, WebP for Variations

## Context
Bulk image generation produces potentially hundreds of image variations per run. Storing every image in uncompressed or lossless PNG consumes substantial disk space and bandwidth, but compressing the seed image early could degrade visual fidelity when used as the reference ancestor for multiple subsequent generations.

## Decision
We decided to save candidate and seed images in lossless **PNG** format, and save all generated variations in **WebP** format.

## Consequences
- **Positive**: Guarantees maximum fidelity for the seed ancestor while achieving significant disk space savings and web-readiness for high-volume batch variations.
- **Negative**: Requires handling different image encoders and extension naming (`.png` vs `.webp`) across the two phases.
