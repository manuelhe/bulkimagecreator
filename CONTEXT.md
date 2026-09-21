# Bulk Image Creator

A command-line tool that transforms reference images into a curated seed image, then traverses a prompt catalog to generate a batch of image variations.

## Language

**Source Image**:
One of 1 to 4 user-supplied reference images provided as initial visual input to establish context.
_Avoid_: Input image, reference photo

**Seed Prompt**:
The text prompt supplied during the seed phase to generate candidate seed images.
_Avoid_: Initial prompt, base prompt, starting prompt

**Candidate Image**:
An unaccepted image generated during the seed phase presented to the user for evaluation and approval.
_Avoid_: Draft image, trial image, preview image

**Seed Image**:
The single accepted image output from the seed phase that serves as the visual ancestor for all variations.
_Avoid_: Base image, root image, master image, initial output

**Seed Phase**:
The interactive phase where candidate images are repeatedly generated from source images and refined until the user accepts one.
_Avoid_: Phase 1, calibration phase, setup loop

**Prompt Template**:
A formatting pattern containing `{prompt}` applied to each variation prompt during the variation phase.
_Avoid_: Prompt wrapper, prompt prefix, macro

**Variation Prompt**:
A text prompt from a prompt list used during the variation phase to generate a new image derived from the seed image.
_Avoid_: Batch prompt, secondary prompt, child prompt

**Variation Phase**:
The automated traversal phase that iterates through variation prompts to produce variations, skipping non-recoverable failures.
_Avoid_: Batch phase, stage 2, loop phase

**Run**:
A single end-to-end execution of the application, encompassing both the seed phase and the variation phase.
_Avoid_: Job, session, task

**Run Manifest**:
A structured file stored inside a run folder documenting the source images, prompts, output paths, and failure logs for that run.
_Avoid_: Metadata, log dump, run summary
