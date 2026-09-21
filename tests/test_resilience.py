"""Tests for rate-limit pacing, exponential backoff, fault skipping, and resilience."""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch
from PIL import Image
import pytest
from typer.testing import CliRunner

from bulkimagecreator.cli import app
from bulkimagecreator.manifest import create_initial_manifest, load_manifest, save_manifest
from bulkimagecreator.models import RunConfig, RunStatus, VariationExecutionStatus
from bulkimagecreator.service import MockImageGenerationService
from bulkimagecreator.storage import create_run_directory
from bulkimagecreator.variation_phase import run_variation_phase


@pytest.fixture
def run_fixture(tmp_path: Path):
    """Fixture providing an initialized run directory, manifest, and seed image."""
    base_dir = tmp_path / "runs"
    run_id, run_dir = create_run_directory(base_dir=base_dir, run_id="test-run")

    source_file = tmp_path / "source.png"
    Image.new("RGB", (64, 64), color="blue").save(source_file, format="PNG")

    manifest = create_initial_manifest(
        run_id="test-run",
        config=RunConfig(aspect_ratio="1:1", model="gemini-2.5-flash-image"),
        sources=[],
    )

    seed_file = run_dir / "00_seed.png"
    Image.new("RGB", (64, 64), color="green").save(seed_file, format="PNG")
    manifest.seed_phase.accepted_candidate = 1
    save_manifest(manifest, run_dir)

    return run_dir, manifest, seed_file


def test_transient_429_retried_with_backoff_and_succeeds(run_fixture) -> None:
    """A transient 429 error triggers exponential backoff and succeeds on retry."""
    run_dir, manifest, seed_file = run_fixture
    service = MockImageGenerationService()
    service.set_transient_failure_for_prompt("Retryable prompt", retries_before_success=1)

    sleep_calls: list[float] = []

    saved_paths = run_variation_phase(
        run_dir=run_dir,
        manifest=manifest,
        service=service,
        seed_image_path=seed_file,
        prompt_inputs=["Retryable prompt"],
        delay=0.0,
        max_retries=2,
        initial_backoff=1.0,
        sleeper=sleep_calls.append,
    )

    # 1 retry performed with backoff delay of 1.0s
    assert sleep_calls == [1.0]
    assert len(saved_paths) == 1
    assert saved_paths[0] == run_dir / "01_variation.webp"
    assert saved_paths[0].is_file()

    # Verify manifest
    reloaded = load_manifest(run_dir)
    assert len(reloaded.variations) == 1
    var = reloaded.variations[0]
    assert var.index == 1
    assert var.status == VariationExecutionStatus.SUCCESS
    assert var.output_filename == "01_variation.webp"
    assert var.error is None
    assert reloaded.status == RunStatus.COMPLETED


def test_transient_429_exhausts_retries_and_is_skipped(run_fixture) -> None:
    """A transient 429 error exhausts all retries and marks variation as skipped with diagnostic."""
    run_dir, manifest, seed_file = run_fixture
    service = MockImageGenerationService()
    service.set_transient_failure_for_prompt("Exhausted prompt", retries_before_success=5)

    sleep_calls: list[float] = []

    saved_paths = run_variation_phase(
        run_dir=run_dir,
        manifest=manifest,
        service=service,
        seed_image_path=seed_file,
        prompt_inputs=["Exhausted prompt"],
        delay=0.0,
        max_retries=2,
        initial_backoff=1.0,
        sleeper=sleep_calls.append,
    )

    # 2 retries performed: 1.0s and 2.0s
    assert sleep_calls == [1.0, 2.0]
    assert len(saved_paths) == 0
    assert not (run_dir / "01_variation.webp").exists()

    # Verify manifest has skipped record
    reloaded = load_manifest(run_dir)
    assert len(reloaded.variations) == 1
    var = reloaded.variations[0]
    assert var.index == 1
    assert var.status == VariationExecutionStatus.SKIPPED
    assert var.output_filename is None
    assert var.error is not None
    assert "Transient error retries exhausted" in var.error
    assert "429" in var.error
    assert reloaded.status == RunStatus.COMPLETED


def test_safety_block_skipped_immediately_without_retries(run_fixture) -> None:
    """A safety block error skips immediately without attempting retries."""
    run_dir, manifest, seed_file = run_fixture
    service = MockImageGenerationService()
    service.set_safety_block_for_prompt(
        "Unsafe prompt", error_message="Generation blocked by safety policy (finish_reason=SAFETY)"
    )

    sleep_calls: list[float] = []

    saved_paths = run_variation_phase(
        run_dir=run_dir,
        manifest=manifest,
        service=service,
        seed_image_path=seed_file,
        prompt_inputs=["Unsafe prompt"],
        delay=0.0,
        max_retries=2,
        initial_backoff=1.0,
        sleeper=sleep_calls.append,
    )

    # No retries or sleeps
    assert sleep_calls == []
    assert len(saved_paths) == 0
    assert len(service.call_history) == 1

    # Verify manifest
    reloaded = load_manifest(run_dir)
    assert len(reloaded.variations) == 1
    var = reloaded.variations[0]
    assert var.index == 1
    assert var.status == VariationExecutionStatus.SKIPPED
    assert var.output_filename is None
    assert var.error is not None
    assert "safety policy" in var.error
    assert reloaded.status == RunStatus.COMPLETED


def test_mixed_batch_execution(run_fixture) -> None:
    """Mixed batch test verifying success, safety block, transient retry, and subsequent success."""
    run_dir, manifest, seed_file = run_fixture
    service = MockImageGenerationService()

    prompts = [
        "Prompt 1 Normal",
        "Prompt 2 Unsafe",
        "Prompt 3 RateLimited",
        "Prompt 4 Normal",
    ]

    service.set_safety_block_for_prompt(
        "Prompt 2 Unsafe",
        error_message="Prompt blocked by safety filters",
    )
    service.set_transient_failure_for_prompt(
        "Prompt 3 RateLimited",
        retries_before_success=1,
    )

    sleep_calls: list[float] = []

    saved_paths = run_variation_phase(
        run_dir=run_dir,
        manifest=manifest,
        service=service,
        seed_image_path=seed_file,
        prompt_inputs=prompts,
        delay=0.5,
        max_retries=2,
        initial_backoff=1.0,
        sleeper=sleep_calls.append,
    )

    # Output paths should only include successful generations
    assert len(saved_paths) == 3
    assert (run_dir / "01_variation.webp").is_file()
    assert not (run_dir / "02_variation.webp").exists()
    assert (run_dir / "03_variation.webp").is_file()
    assert (run_dir / "04_variation.webp").is_file()

    # Sleep verification:
    # 1. After item 1: delay 0.5s
    # 2. After item 2: delay 0.5s
    # 3. During item 3: backoff retry 1.0s
    # 4. After item 3: delay 0.5s
    # 5. After item 4 (last item): no pacing sleep
    assert sleep_calls == [0.5, 0.5, 1.0, 0.5]

    # Verify manifest contents
    reloaded = load_manifest(run_dir)
    assert len(reloaded.variations) == 4

    v1, v2, v3, v4 = reloaded.variations

    assert v1.index == 1
    assert v1.status == VariationExecutionStatus.SUCCESS
    assert v1.output_filename == "01_variation.webp"
    assert v1.error is None

    assert v2.index == 2
    assert v2.status == VariationExecutionStatus.SKIPPED
    assert v2.output_filename is None
    assert "Prompt blocked by safety filters" in (v2.error or "")

    assert v3.index == 3
    assert v3.status == VariationExecutionStatus.SUCCESS
    assert v3.output_filename == "03_variation.webp"
    assert v3.error is None

    assert v4.index == 4
    assert v4.status == VariationExecutionStatus.SUCCESS
    assert v4.output_filename == "04_variation.webp"
    assert v4.error is None

    assert reloaded.status == RunStatus.COMPLETED


def test_delay_pacing_applied_between_requests(run_fixture) -> None:
    """Inter-request pacing delay is applied between calls, omitting the final item."""
    run_dir, manifest, seed_file = run_fixture
    service = MockImageGenerationService()

    prompts = ["A", "B", "C"]
    sleep_calls: list[float] = []

    run_variation_phase(
        run_dir=run_dir,
        manifest=manifest,
        service=service,
        seed_image_path=seed_file,
        prompt_inputs=prompts,
        delay=2.5,
        sleeper=sleep_calls.append,
    )

    # 2 pacing sleeps between 3 items
    assert sleep_calls == [2.5, 2.5]


def test_cli_runner_integration_mixed_batch(tmp_path: Path) -> None:
    """Full CLI runner integration test verifying mixed batch fault skipping and terminal summary."""
    runner = CliRunner()

    source_path = tmp_path / "source1.png"
    Image.new("RGB", (64, 64), color="navy").save(source_path, format="PNG")

    prompts_file = tmp_path / "prompts.txt"
    prompts_file.write_text(
        "A cyberpunk cat\n"
        "# Comment line\n"
        "A toxic radioactive dog\n"
        "A neon rabbit\n",
        encoding="utf-8",
    )

    runs_dir = tmp_path / "runs"

    mock_service = MockImageGenerationService()
    mock_service.set_safety_block_for_prompt("A toxic radioactive dog", error_message="Safety policy block")
    mock_service.set_transient_failure_for_prompt("A neon rabbit", retries_before_success=1)

    with patch("bulkimagecreator.cli.GeminiImageGenerationService", return_value=mock_service):
        result = runner.invoke(
            app,
            [
                "run",
                str(source_path),
                "--output-dir",
                str(runs_dir),
                "--prompt",
                "A baseline robot",
                "--prompts-file",
                str(prompts_file),
                "--delay",
                "0.01",
                "--no-open",
            ],
            input="a\n",
        )

    assert result.exit_code == 0, f"CLI exited with {result.exit_code}: {result.output}"

    # Verify summary table presence in output
    assert "Variation Phase - Execution Summary" in result.output
    assert "Total Prompts" in result.output
    assert "Successful Images" in result.output
    assert "Skipped Prompts" in result.output

    # Find created run directory
    run_folders = list(runs_dir.iterdir())
    assert len(run_folders) == 1
    run_folder = run_folders[0]

    reloaded_manifest = load_manifest(run_folder)
    assert reloaded_manifest.status == RunStatus.COMPLETED
    assert len(reloaded_manifest.variations) == 3

    v1, v2, v3 = reloaded_manifest.variations
    assert v1.status == VariationExecutionStatus.SUCCESS
    assert v1.output_filename == "01_variation.webp"
    assert (run_folder / "01_variation.webp").is_file()

    assert v2.status == VariationExecutionStatus.SKIPPED
    assert v2.output_filename is None
    assert not (run_folder / "02_variation.webp").exists()

    assert v3.status == VariationExecutionStatus.SUCCESS
    assert v3.output_filename == "03_variation.webp"
    assert (run_folder / "03_variation.webp").is_file()
