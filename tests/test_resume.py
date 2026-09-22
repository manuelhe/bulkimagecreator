"""Integration and unit tests for batch interruption recovery (resume command)."""

import io
from pathlib import Path
from PIL import Image
import pytest
from typer.testing import CliRunner

from bulkimagecreator.cli import app, set_image_service
from bulkimagecreator.exceptions import ValidationError
from bulkimagecreator.manifest import (
    create_initial_manifest,
    load_manifest,
    save_manifest,
)
from bulkimagecreator.models import (
    RunConfig,
    RunManifest,
    RunStatus,
    VariationExecutionStatus,
    VariationRecord,
)
from bulkimagecreator.service import MockImageGenerationService
from bulkimagecreator.variation_phase import resume_variation_phase


@pytest.fixture
def test_seed_image(tmp_path: Path) -> Path:
    """Create a dummy 00_seed.png image."""
    img_path = tmp_path / "seed_fixture.png"
    img = Image.new("RGB", (100, 100), color="blue")
    img.save(img_path, format="PNG")
    return img_path


@pytest.fixture
def mock_service() -> MockImageGenerationService:
    """Fixture providing a clean MockImageGenerationService instance."""
    return MockImageGenerationService()


class TestResumeValidation:
    """Tests validating prerequisites for resuming runs."""

    def test_resume_non_existent_directory(
        self, tmp_path: Path, mock_service: MockImageGenerationService
    ) -> None:
        """Assert ValidationError raised when run directory does not exist."""
        non_existent = tmp_path / "run_does_not_exist"
        with pytest.raises(ValidationError, match="Run directory not found"):
            resume_variation_phase(
                run_dir=non_existent,
                service=mock_service,
            )

    def test_resume_missing_manifest(
        self, tmp_path: Path, mock_service: MockImageGenerationService
    ) -> None:
        """Assert ValidationError raised when run_manifest.json is missing."""
        run_dir = tmp_path / "run_missing_manifest"
        run_dir.mkdir(parents=True, exist_ok=True)
        with pytest.raises(ValidationError, match="Run manifest not found"):
            resume_variation_phase(
                run_dir=run_dir,
                service=mock_service,
            )

    def test_resume_missing_seed_image(
        self, tmp_path: Path, mock_service: MockImageGenerationService
    ) -> None:
        """Assert ValidationError raised when 00_seed.png is missing."""
        run_dir = tmp_path / "run_missing_seed"
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest = create_initial_manifest(run_id="run_missing_seed", config=RunConfig(), sources=[])
        save_manifest(manifest, run_dir)

        with pytest.raises(ValidationError, match="Seed image .* not found"):
            resume_variation_phase(
                run_dir=run_dir,
                service=mock_service,
            )


class TestResumeExecution:
    """Tests verifying resumption logic, file preservation, and manifest updates."""

    def test_resume_executes_only_pending_prompts_and_preserves_existing(
        self, tmp_path: Path, test_seed_image: Path, mock_service: MockImageGenerationService
    ) -> None:
        """Assert resume generates only pending prompts without overwriting completed ones."""
        run_dir = tmp_path / "run_partial"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Place 00_seed.png in run directory
        seed_target = run_dir / "00_seed.png"
        seed_target.write_bytes(test_seed_image.read_bytes())

        # Create existing variations 01 and 02 with known content
        var1_path = run_dir / "01_variation.webp"
        var2_path = run_dir / "02_variation.webp"
        var1_bytes = b"ORIGINAL_VAR_1_BYTES"
        var2_bytes = b"ORIGINAL_VAR_2_BYTES"
        var1_path.write_bytes(var1_bytes)
        var2_path.write_bytes(var2_bytes)

        # Construct manifest in INTERRUPTED state with 5 items
        config = RunConfig(delay=0.0, prompt_template="Variation: {prompt}")
        manifest = create_initial_manifest(run_id="run_partial", config=config, sources=[])
        manifest.status = RunStatus.INTERRUPTED
        manifest.variations = [
            VariationRecord(
                index=1,
                prompt="Prompt 1",
                expanded_prompt="Variation: Prompt 1",
                status=VariationExecutionStatus.SUCCESS,
                output_filename="01_variation.webp",
            ),
            VariationRecord(
                index=2,
                prompt="Prompt 2",
                expanded_prompt="Variation: Prompt 2",
                status=VariationExecutionStatus.SUCCESS,
                output_filename="02_variation.webp",
            ),
            VariationRecord(
                index=3,
                prompt="Prompt 3",
                expanded_prompt="Variation: Prompt 3",
                status=VariationExecutionStatus.PENDING,
            ),
            VariationRecord(
                index=4,
                prompt="Prompt 4",
                expanded_prompt="Variation: Prompt 4",
                status=VariationExecutionStatus.PENDING,
            ),
            VariationRecord(
                index=5,
                prompt="Prompt 5",
                expanded_prompt="Variation: Prompt 5",
                status=VariationExecutionStatus.PENDING,
            ),
        ]
        save_manifest(manifest, run_dir)

        # Execute resume
        result_paths = resume_variation_phase(
            run_dir=run_dir,
            service=mock_service,
            delay=0.0,
        )

        assert len(result_paths) == 5

        # 1. Verify existing files were NOT overwritten
        assert var1_path.read_bytes() == var1_bytes
        assert var2_path.read_bytes() == var2_bytes

        # 2. Verify only pending items (3, 4, 5) were requested from service
        assert len(mock_service.call_history) == 3
        requested_prompts = [c["prompt"] for c in mock_service.call_history]
        assert requested_prompts == [
            "Variation: Prompt 3",
            "Variation: Prompt 4",
            "Variation: Prompt 5",
        ]

        # 3. Verify new variations were created as valid WebP
        for idx in (3, 4, 5):
            var_path = run_dir / f"{idx:02d}_variation.webp"
            assert var_path.is_file()
            with Image.open(var_path) as img:
                assert img.format == "WEBP"

        # 4. Verify manifest reloaded from disk is COMPLETED with all SUCCESS
        reloaded = load_manifest(run_dir)
        assert reloaded.status == RunStatus.COMPLETED
        assert len(reloaded.variations) == 5
        for v in reloaded.variations:
            assert v.status == VariationExecutionStatus.SUCCESS
            assert v.output_filename is not None

    def test_resume_retries_transient_failures_and_keeps_permanent_skips(
        self, tmp_path: Path, test_seed_image: Path, mock_service: MockImageGenerationService
    ) -> None:
        """Assert transient failures are retried on resume, while safety skips remain skipped."""
        run_dir = tmp_path / "run_transient_retry"
        run_dir.mkdir(parents=True, exist_ok=True)

        seed_target = run_dir / "00_seed.png"
        seed_target.write_bytes(test_seed_image.read_bytes())

        var1_path = run_dir / "01_variation.webp"
        var1_path.write_bytes(b"VAR1")

        config = RunConfig(delay=0.0, prompt_template="{prompt}")
        manifest = create_initial_manifest(run_id="run_transient_retry", config=config, sources=[])
        manifest.status = RunStatus.INTERRUPTED
        manifest.variations = [
            VariationRecord(
                index=1,
                prompt="Prompt 1",
                expanded_prompt="Prompt 1",
                status=VariationExecutionStatus.SUCCESS,
                output_filename="01_variation.webp",
            ),
            VariationRecord(
                index=2,
                prompt="Prompt 2 (transient)",
                expanded_prompt="Prompt 2 (transient)",
                status=VariationExecutionStatus.SKIPPED,
                error="Transient error retries exhausted: HTTP 429 Rate limit",
            ),
            VariationRecord(
                index=3,
                prompt="Prompt 3 (safety)",
                expanded_prompt="Prompt 3 (safety)",
                status=VariationExecutionStatus.SKIPPED,
                error="Generation blocked by safety filter",
            ),
        ]
        save_manifest(manifest, run_dir)

        # Resume execution
        resume_variation_phase(
            run_dir=run_dir,
            service=mock_service,
            delay=0.0,
        )

        # Verify: Prompt 2 was retried and succeeded; Prompt 3 was NOT retried
        assert len(mock_service.call_history) == 1
        assert mock_service.call_history[0]["prompt"] == "Prompt 2 (transient)"

        reloaded = load_manifest(run_dir)
        assert reloaded.status == RunStatus.COMPLETED
        assert reloaded.variations[0].status == VariationExecutionStatus.SUCCESS
        assert reloaded.variations[1].status == VariationExecutionStatus.SUCCESS
        assert reloaded.variations[1].output_filename == "02_variation.webp"
        assert reloaded.variations[2].status == VariationExecutionStatus.SKIPPED
        assert reloaded.variations[2].output_filename is None

    def test_resume_when_all_already_completed_exits_cleanly(
        self, tmp_path: Path, test_seed_image: Path, mock_service: MockImageGenerationService
    ) -> None:
        """Assert resume on a fully completed run returns existing files without service calls."""
        run_dir = tmp_path / "run_all_done"
        run_dir.mkdir(parents=True, exist_ok=True)

        seed_target = run_dir / "00_seed.png"
        seed_target.write_bytes(test_seed_image.read_bytes())

        var1_path = run_dir / "01_variation.webp"
        var1_path.write_bytes(b"VAR1")

        config = RunConfig(delay=0.0)
        manifest = create_initial_manifest(run_id="run_all_done", config=config, sources=[])
        manifest.status = RunStatus.COMPLETED
        manifest.variations = [
            VariationRecord(
                index=1,
                prompt="Done Prompt",
                expanded_prompt="Done Prompt",
                status=VariationExecutionStatus.SUCCESS,
                output_filename="01_variation.webp",
            ),
        ]
        save_manifest(manifest, run_dir)

        paths = resume_variation_phase(
            run_dir=run_dir,
            service=mock_service,
            delay=0.0,
        )

        assert len(paths) == 1
        assert paths[0] == var1_path
        assert len(mock_service.call_history) == 0


class TestResumeCliIntegration:
    """CLI integration tests using CliRunner for bulkimagecreator resume."""

    def test_cli_resume_successful_flow(
        self, tmp_path: Path, test_seed_image: Path, mock_service: MockImageGenerationService
    ) -> None:
        """Assert bulkimagecreator resume runs cleanly through CLI."""
        set_image_service(mock_service)
        runner = CliRunner()

        run_dir = tmp_path / "run_cli_resume"
        run_dir.mkdir(parents=True, exist_ok=True)

        seed_target = run_dir / "00_seed.png"
        seed_target.write_bytes(test_seed_image.read_bytes())

        var1 = run_dir / "01_variation.webp"
        var1.write_bytes(b"EXISTING_1")

        config = RunConfig(delay=0.0)
        manifest = create_initial_manifest(run_id="run_cli_resume", config=config, sources=[])
        manifest.status = RunStatus.INTERRUPTED
        manifest.variations = [
            VariationRecord(
                index=1,
                prompt="Prompt 1",
                expanded_prompt="Prompt 1",
                status=VariationExecutionStatus.SUCCESS,
                output_filename="01_variation.webp",
            ),
            VariationRecord(
                index=2,
                prompt="Prompt 2",
                expanded_prompt="Prompt 2",
                status=VariationExecutionStatus.PENDING,
            ),
        ]
        save_manifest(manifest, run_dir)

        result = runner.invoke(app, ["resume", str(run_dir), "--delay", "0.0"])

        assert result.exit_code == 0
        assert "Resuming Variation Phase" in result.output
        assert "Variation Phase - Resume Summary" in result.output
        assert (run_dir / "02_variation.webp").is_file()

        reloaded = load_manifest(run_dir)
        assert reloaded.status == RunStatus.COMPLETED

    def test_cli_resume_rejects_missing_directory(self, tmp_path: Path) -> None:
        """Assert CLI exits with code 1 when given a non-existent directory."""
        runner = CliRunner()
        result = runner.invoke(app, ["resume", str(tmp_path / "ghost_dir")])
        assert result.exit_code == 1
        assert "Run directory not found" in result.output

    def test_cli_resume_rejects_missing_manifest(self, tmp_path: Path) -> None:
        """Assert CLI exits with code 1 when manifest is missing."""
        runner = CliRunner()
        empty_dir = tmp_path / "empty_run"
        empty_dir.mkdir()
        result = runner.invoke(app, ["resume", str(empty_dir)])
        assert result.exit_code == 1
        assert "Run manifest not found in" in result.output

    def test_cli_resume_rejects_missing_seed_image(self, tmp_path: Path) -> None:
        """Assert CLI exits with code 1 when 00_seed.png is missing."""
        runner = CliRunner()
        run_dir = tmp_path / "no_seed_run"
        run_dir.mkdir()
        manifest = create_initial_manifest(run_id="no_seed_run", config=RunConfig(), sources=[])
        save_manifest(manifest, run_dir)

        result = runner.invoke(app, ["resume", str(run_dir)])
        assert result.exit_code == 1
        assert "Seed image (00_seed.png) not found in" in result.output

    def test_resume_with_prompts_file_appends_extra_prompts_with_continuous_indices(
        self, tmp_path: Path, test_seed_image: Path, mock_service: MockImageGenerationService
    ) -> None:
        """Assert resume with prompts_file correctly adds new prompts with non-colliding continuous indices."""
        run_dir = tmp_path / "run_extra_prompts"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "00_seed.png").write_bytes(test_seed_image.read_bytes())
        (run_dir / "01_variation.webp").write_bytes(b"EXISTING_1")

        manifest = create_initial_manifest(run_id="run_extra_prompts", config=RunConfig(delay=0.0), sources=[])
        manifest.status = RunStatus.INTERRUPTED
        manifest.variations = [
            VariationRecord(
                index=1,
                prompt="Prompt 1",
                expanded_prompt="Prompt 1",
                status=VariationExecutionStatus.SUCCESS,
                output_filename="01_variation.webp",
            )
        ]
        save_manifest(manifest, run_dir)

        prompts_file = tmp_path / "extra_prompts.txt"
        prompts_file.write_text("Prompt 1\nPrompt 2\nPrompt 3\n")

        res = resume_variation_phase(
            run_dir=run_dir,
            service=mock_service,
            prompts_file=prompts_file,
            delay=0.0,
        )

        assert len(res) == 3
        reloaded = load_manifest(run_dir)
        assert len(reloaded.variations) == 3
        assert reloaded.variations[0].index == 1
        assert reloaded.variations[1].index == 2
        assert reloaded.variations[2].index == 3
        assert (run_dir / "02_variation.webp").is_file()
        assert (run_dir / "03_variation.webp").is_file()

    def test_transient_failure_records_is_transient_flag(
        self, tmp_path: Path, test_seed_image: Path, mock_service: MockImageGenerationService
    ) -> None:
        """Assert is_transient flag is True on transient exhaustion and False on safety block."""
        run_dir = tmp_path / "run_flags"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "00_seed.png").write_bytes(test_seed_image.read_bytes())

        manifest = create_initial_manifest(run_id="run_flags", config=RunConfig(delay=0.0), sources=[])
        manifest.variations = [
            VariationRecord(index=1, prompt="Rate limit fail", expanded_prompt="Rate limit fail"),
            VariationRecord(index=2, prompt="Safety block", expanded_prompt="Safety block"),
        ]
        save_manifest(manifest, run_dir)

        mock_service.set_transient_failure_for_prompt("Rate limit fail", retries_before_success=99)
        mock_service.set_safety_block_for_prompt("Safety block")

        resume_variation_phase(run_dir=run_dir, service=mock_service, delay=0.0)

        reloaded = load_manifest(run_dir)
        rec1 = reloaded.variations[0]
        rec2 = reloaded.variations[1]

        assert rec1.status == VariationExecutionStatus.SKIPPED
        assert rec1.is_transient is True

        assert rec2.status == VariationExecutionStatus.SKIPPED
        assert rec2.is_transient is False
