# 04: Rate-Limit Pacing, Exponential Backoff, and Non-Transient Fault Skipping

**What to build:**
Hardens the variation batch traversal against real-world API conditions: applies an inter-request pacing delay (`--delay`, default 1.5s), automatically intercepts transient failures (HTTP 429 rate limits, HTTP 503 service unavailable, timeouts) with exponential backoff (up to 2 retries), and immediately skips non-transient failures (safety filter blocks, policy rejections) without crashing the batch. Diagnostic failure details are logged to `run_manifest.json` so the batch achieves maximum possible yield.

**Blocked by:** 03: Variation Phase Batch Traversal, WebP Encoding, and Live Progress (#4)

**Status:** completed

- [x] Paces API requests with configurable delay (`--delay`, default 1.5 seconds) between calls
- [x] Catches transient API errors (HTTP 429, HTTP 503, connection timeouts) and retries with exponential backoff up to 2 times
- [x] Catches non-transient API errors (safety ratings, content filters, recitation blocks) and skips to next prompt immediately without halting the batch
- [x] Logs failure category and diagnostic message in `run_manifest.json` for each skipped prompt
- [x] Terminal summary table and progress bar reflect both successful images and skipped prompts
- [x] Test suite verifies backoff recovery on 429 errors and immediate skipping on safety blocks without aborting the batch
