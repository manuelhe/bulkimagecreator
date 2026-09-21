# 0001. Seed-Only Image Lineage for Variation Phase

## Context
In the two-phase workflow, the application generates a batch of image variations in the variation phase following an initial seed phase. The model could either receive all 1 to 4 original source images alongside the accepted seed image, or receive exclusively the seed image as its visual input.

## Decision
We decided that the variation phase passes exclusively the accepted `Seed Image` (along with the formatted `Variation Prompt`) to the model, excluding the original 1 to 4 source images.

## Consequences
- **Positive**: Maintains strict visual consistency across the batch, minimizes multimodal token quota/costs, and prevents the model from conflating raw source reference elements with the synthesized seed composition.
- **Negative**: If a variation prompt specifically refers to an element from an original source image that was not preserved in the seed image, the model will not have access to that original source.
