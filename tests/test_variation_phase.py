"""Comprehensive tests for the Variation Phase batch traversal, WebP encoding, and live progress."""

from pathlib import Path
from unittest.mock import patch
from PIL import Image
import pytest
from typer.testing import CliRunner

from bulkimagecreator.cli import app, set_image_service
from bulkimagecreator.exceptions import ValidationError
from bulkimagecreator.manifest import create_initial_manifest, load_manifest, save_manifest
from bulkimagecreator.models import (
    RunConfig,
    RunStatus,
    VariationExecutionStatus,
)
from bulkimagecreator.service import MockImageGenerationService
from bulkimagecreator.variation_phase import (
    format_variation_prompt,
    load_variation_prompts,
    run_variation_phase,
)

runner = CliRunner()


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    """Fixture creating a temporary valid source image."""
    img_path = tmp_path / "source.png"
    img = Image.new("RGB", (64, 64), color="blue")
    img.save(img_path, format="PNG")
    return img_path


@pytest.fixture
def seed_image(tmp_path: Path) -> Path:
    """Fixture creating a temporary valid seed image."""
    seed_path = tmp_path / "00_seed.png"
    img = Image.new("RGB", (64, 64), color="green")
    img.save(seed_path, format="PNG")
    return seed_path


@pytest.fixture(autouse=True)
def configure_mock_service():
    """Ensure MockImageGenerationService is active for all tests."""
    mock = MockImageGenerationService()
    set_image_service(mock)
    yield mock
    set_image_service(None)


class TestPromptLoading:
    """Tests for loading and sanitizing variation prompts."""

    def test_load_variation_prompts_file_strips_comments_and_blanks(self, tmp_path: Path) -> None:
        """Assert comments and empty lines are stripped while valid prompts are preserved."""
        prompts_file = tmp_path / "prompts.txt"
        prompts_file.write_text(
            "# Line 1: Comment header\n"
            "\n"
            "Cinematic neon city\n"
            "  # Mid-file comment\n"
            "   Steampunk airship in sunset   \n"
            "\n"
            "Undersea coral reef\n"
            "# Trailing comment\n",
            encoding="utf-8",
        )

        prompts = load_variation_prompts(prompts_file=prompts_file)
        assert prompts == [
            "Cinematic neon city",
            "Steampunk airship in sunset",
            "Undersea coral reef",
        ]

    def test_load_variation_prompts_file_not_found(self, tmp_path: Path) -> None:
        """Assert non-existent prompts file raises ValidationError."""
        missing_file = tmp_path / "non_existent_prompts.txt"
        with pytest.raises(ValidationError, match="Prompts file not found"):
            load_variation_prompts(prompts_file=missing_file)

    def test_load_variation_prompts_from_list(self) -> None:
        """Assert prompt_inputs list is stripped and filtered for comments and blanks."""
        raw_inputs = [
            "# Ignore comment",
            "   ",
            "A majestic dragon",
            "  A floating castle  ",
            "",
            "# Another comment",
        ]
        prompts = load_variation_prompts(prompt_inputs=raw_inputs)
        assert prompts == ["A majestic dragon", "A floating castle"]

    def test_load_variation_prompts_interactive_path(self, tmp_path: Path) -> None:
        """Assert interactive mode successfully reads prompts when user inputs file path."""
        prompts_file = tmp_path / "interactive_prompts.txt"
        prompts_file.write_text("Prompt Alpha\nPrompt Beta\n", encoding="utf-8")

        with patch("rich.prompt.Prompt.ask", return_value=str(prompts_file)):
            prompts = load_variation_prompts()

        assert prompts == ["Prompt Alpha", "Prompt Beta"]

    def test_load_variation_prompts_interactive_manual_lines(self) -> None:
        """Assert interactive mode collects manual lines when path is empty."""
        inputs = iter(["", "First manual prompt", "Second manual prompt", ""])
        with patch("rich.prompt.Prompt.ask", side_effect=lambda *args, **kwargs: next(inputs)):
            prompts = load_variation_prompts()

        assert prompts == ["First manual prompt", "Second manual prompt"]

    def test_load_variation_prompts_interactive_cancellation_eof(self) -> None:
        """Assert EOFError during interactive prompt returns empty list cleanly."""
        with patch("rich.prompt.Prompt.ask", side_effect=EOFError):
            prompts = load_variation_prompts()

        assert prompts == []


class TestPromptTemplateFormatting:
    """Tests for validating and formatting variation prompts with templates."""

    def test_format_variation_prompt_default_template(self) -> None:
        """Assert default '{prompt}' template leaves prompt untouched."""
        result = format_variation_prompt("snowy landscape", template="{prompt}")
        assert result == "snowy landscape"

    def test_format_variation_prompt_custom_template(self) -> None:
        """Assert custom template substitutes '{prompt}' placeholder correctly."""
        template = "A vibrant watercolor painting of {prompt}, trending on artstation"
        result = format_variation_prompt("an ancient oak tree", template=template)
        assert result == "A vibrant watercolor painting of an ancient oak tree, trending on artstation"

    def test_format_variation_prompt_strips_prompt_whitespace(self) -> None:
        """Assert leading and trailing whitespace in raw prompt is stripped during substitution."""
        template = "Isometric 3D model of {prompt}"
        result = format_variation_prompt("   space station   ", template=template)
        assert result == "Isometric 3D model of space station"

    def test_format_variation_prompt_missing_placeholder_raises_validation_error(self) -> None:
        """Assert template without '{prompt}' placeholder raises ValidationError."""
        with pytest.raises(ValidationError, match="must contain '{prompt}' placeholder"):
            format_variation_prompt("a prompt", template="A style without placeholder")


class TestVariationPhaseTraversal:
    """Tests for batch traversal, WebP encoding, and manifest synchronization."""

    def test_batch_traversal_sequential_webp_files_and_manifest(
        self, tmp_path: Path, configure_mock_service: MockImageGenerationService
    ) -> None:
        """Assert variations are sequentially numbered WebP files derived exclusively from 00_seed.png."""
        run_dir = tmp_path / "run_20260921_180000"
        run_dir.mkdir(parents=True, exist_ok=True)

        seed_file = run_dir / "00_seed.png"
        Image.new("RGB", (64, 64), color="forestgreen").save(seed_file, format="PNG")

        manifest = create_initial_manifest(
            run_id=run_dir.name,
            config=RunConfig(prompt_template="Digital render of {prompt}"),
            sources=[],
        )
        save_manifest(manifest, run_dir)

        prompts = [
            "Crystal cavern",
            "Volcanic ridge",
            "Sunlit meadow",
        ]

        saved_paths = run_variation_phase(
            run_dir=run_dir,
            manifest=manifest,
            service=configure_mock_service,
            seed_image_path=seed_file,
            prompt_inputs=prompts,
            prompt_template="Digital render of {prompt}",
            delay=0.0,
        )

        assert len(saved_paths) == 3

        # 1. Sequential numbering: 01_variation.webp, 02_variation.webp, 03_variation.webp
        expected_names = ["01_variation.webp", "02_variation.webp", "03_variation.webp"]
        for expected_name, saved_path in zip(expected_names, saved_paths):
            assert saved_path.name == expected_name
            assert saved_path.is_file()
            assert saved_path.stat().st_size > 0

            # 2. ADR 0002: Verify file is a valid WebP image readable by Pillow
            with Image.open(saved_path) as img:
                assert img.format == "WEBP"

        # 3. ADR 0001: Verify service was called with exclusively 00_seed.png
        assert len(configure_mock_service.call_history) == 3
        for call in configure_mock_service.call_history:
            assert call["reference_images"] == [seed_file]

        assert configure_mock_service.call_history[0]["prompt"] == "Digital render of Crystal cavern"
        assert configure_mock_service.call_history[1]["prompt"] == "Digital render of Volcanic ridge"
        assert configure_mock_service.call_history[2]["prompt"] == "Digital render of Sunlit meadow"

        # 4. Verify run_manifest.json updated atomically and status set to completed
        assert manifest.status == RunStatus.COMPLETED
        assert len(manifest.variations) == 3

        for idx, (prompt_text, expected_name) in enumerate(zip(prompts, expected_names), start=1):
            var_record = manifest.variations[idx - 1]
            assert var_record.index == idx
            assert var_record.prompt == prompt_text
            assert var_record.expanded_prompt == f"Digital render of {prompt_text}"
            assert var_record.status == VariationExecutionStatus.SUCCESS
            assert var_record.output_filename == expected_name

        # 5. Reload manifest from disk to verify persistence
        disk_manifest = load_manifest(run_dir)
        assert disk_manifest.status == RunStatus.COMPLETED
        assert len(disk_manifest.variations) == 3
        assert disk_manifest.variations[0].output_filename == "01_variation.webp"
        assert disk_manifest.variations[1].output_filename == "02_variation.webp"
        assert disk_manifest.variations[2].output_filename == "03_variation.webp"

    def test_run_variation_phase_missing_seed_image_raises_validation_error(
        self, tmp_path: Path, configure_mock_service: MockImageGenerationService
    ) -> None:
        """Assert missing seed image file raises ValidationError."""
        run_dir = tmp_path / "run_missing_seed"
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest = create_initial_manifest(run_id=run_dir.name, config=RunConfig(), sources=[])

        missing_seed = run_dir / "00_seed.png"
        with pytest.raises(ValidationError, match="Seed image not found"):
            run_variation_phase(
                run_dir=run_dir,
                manifest=manifest,
                service=configure_mock_service,
                seed_image_path=missing_seed,
                prompt_inputs=["Any prompt"],
            )

    def test_run_variation_phase_empty_prompts_exits_cleanly(
        self, tmp_path: Path, configure_mock_service: MockImageGenerationService
    ) -> None:
        """Assert empty prompt list returns empty list without error or changing status to completed."""
        run_dir = tmp_path / "run_empty"
        run_dir.mkdir(parents=True, exist_ok=True)
        seed_file = run_dir / "00_seed.png"
        Image.new("RGB", (32, 32), color="red").save(seed_file, format="PNG")

        manifest = create_initial_manifest(run_id=run_dir.name, config=RunConfig(), sources=[])
        saved_paths = run_variation_phase(
            run_dir=run_dir,
            manifest=manifest,
            service=configure_mock_service,
            seed_image_path=seed_file,
            prompt_inputs=[],
        )

        assert saved_paths == []
        assert manifest.status == RunStatus.IN_PROGRESS
        assert len(manifest.variations) == 0


class TestCliEndToEndIntegration:
    """Full CLI integration tests exercising Seed Phase acceptance through Variation Phase traversal."""

    def test_cli_seed_and_variation_phases_with_prompts_file(
        self, tmp_path: Path, sample_image: Path, configure_mock_service: MockImageGenerationService
    ) -> None:
        """Assert CLI run command completes both Seed Phase and Variation Phase with --prompts-file."""
        out_dir = tmp_path / "runs"
        prompts_file = tmp_path / "batch_prompts.txt"
        prompts_file.write_text(
            "# Variation prompts batch\n"
            "Emerald forest at dawn\n"
            "Snowy peak under aurora\n",
            encoding="utf-8",
        )

        # User input: 'a' accepts candidate #1 during Seed Phase
        user_input = "a\n"

        with patch("bulkimagecreator.seed_phase.launch_viewer"):
            result = runner.invoke(
                app,
                [
                    "run",
                    str(sample_image),
                    "--output-dir",
                    str(out_dir),
                    "--prompt",
                    "A fantasy landscape",
                    "-f",
                    str(prompts_file),
                    "-t",
                    "Style: {prompt}",
                    "--delay",
                    "0",
                    "--no-open",
                ],
                input=user_input,
            )

        assert result.exit_code == 0
        assert "Generating candidate #1" in result.output
        assert "Accepted candidate #1 as seed image: 00_seed.png" in result.output
        assert "Starting Variation Phase: 2 prompt(s) to process" in result.output
        assert "Variation Phase - Execution Summary" in result.output
        assert "Total Prompts" in result.output
        assert "Successful Images" in result.output

        # Verify run folder structure
        run_dirs = list(out_dir.glob("run_*"))
        assert len(run_dirs) == 1
        run_dir = run_dirs[0]

        # Verify seed image exists and is PNG
        seed_path = run_dir / "00_seed.png"
        assert seed_path.is_file()
        with Image.open(seed_path) as img:
            assert img.format == "PNG"

        # Verify variation images exist and are WebP (ADR 0002)
        var1 = run_dir / "01_variation.webp"
        var2 = run_dir / "02_variation.webp"
        assert var1.is_file()
        assert var2.is_file()

        with Image.open(var1) as img1:
            assert img1.format == "WEBP"
        with Image.open(var2) as img2:
            assert img2.format == "WEBP"

        # ADR 0001: Candidate call had source image, both variation calls had exclusively 00_seed.png
        assert len(configure_mock_service.call_history) == 3
        # Call 1 (Candidate): reference_images is source image
        assert len(configure_mock_service.call_history[0]["reference_images"]) == 1
        assert "source.png" in str(configure_mock_service.call_history[0]["reference_images"][0])
        # Calls 2 and 3 (Variations): reference_images is exclusively 00_seed.png
        assert configure_mock_service.call_history[1]["reference_images"] == [seed_path]
        assert configure_mock_service.call_history[2]["reference_images"] == [seed_path]
        assert configure_mock_service.call_history[1]["prompt"] == "Style: Emerald forest at dawn"
        assert configure_mock_service.call_history[2]["prompt"] == "Style: Snowy peak under aurora"

        # Verify manifest file on disk
        manifest = load_manifest(run_dir)
        assert manifest.status == RunStatus.COMPLETED
        assert manifest.seed_phase.accepted_candidate == 1
        assert len(manifest.variations) == 2
        assert manifest.variations[0].output_filename == "01_variation.webp"
        assert manifest.variations[1].output_filename == "02_variation.webp"

    def test_cli_seed_and_variation_phases_interactive_prompts(
        self, tmp_path: Path, sample_image: Path
    ) -> None:
        """Assert CLI prompts interactively for variation prompts when --prompts-file is omitted."""
        out_dir = tmp_path / "runs"

        # User input sequence:
        # 1. 'a' -> accept candidate #1 in seed phase
        # 2. ''  -> empty file path (triggers manual line input)
        # 3. 'Desert oasis' -> prompt #1
        # 4. 'Frozen lake'  -> prompt #2
        # 5. ''             -> empty line finishes input
        user_input = "a\n\nDesert oasis\nFrozen lake\n\n"

        with patch("bulkimagecreator.seed_phase.launch_viewer"):
            result = runner.invoke(
                app,
                [
                    "run",
                    str(sample_image),
                    "--output-dir",
                    str(out_dir),
                    "--prompt",
                    "Initial landscape",
                    "--delay",
                    "0",
                    "--no-open",
                ],
                input=user_input,
            )

        assert result.exit_code == 0
        assert "Starting Variation Phase: 2 prompt(s) to process" in result.output

        run_dirs = list(out_dir.glob("run_*"))
        assert len(run_dirs) == 1
        run_dir = run_dirs[0]

        var1 = run_dir / "01_variation.webp"
        var2 = run_dir / "02_variation.webp"
        assert var1.is_file()
        assert var2.is_file()

        with Image.open(var1) as img1:
            assert img1.format == "WEBP"
        with Image.open(var2) as img2:
            assert img2.format == "WEBP"

        manifest = load_manifest(run_dir)
        assert manifest.status == RunStatus.COMPLETED
        assert len(manifest.variations) == 2
        assert manifest.variations[0].prompt == "Desert oasis"
        assert manifest.variations[1].prompt == "Frozen lake"

    def test_cli_rejects_invalid_prompt_template(
        self, tmp_path: Path, sample_image: Path
    ) -> None:
        """Assert CLI run command rejects prompt template missing '{prompt}'."""
        result = runner.invoke(
            app,
            [
                "run",
                str(sample_image),
                "-t",
                "Invalid template without placeholder",
            ],
        )

        assert result.exit_code == 1
        assert "Invalid prompt template" in result.output
        assert "{prompt}" in result.output

    def test_cli_rejects_non_existent_prompts_file(
        self, tmp_path: Path, sample_image: Path
    ) -> None:
        """Assert CLI run command rejects non-existent --prompts-file path."""
        result = runner.invoke(
            app,
            [
                "run",
                str(sample_image),
                "-f",
                str(tmp_path / "missing_file.txt"),
            ],
        )

        assert result.exit_code == 1
        assert "Prompts file not found" in result.output
