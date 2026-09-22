"""Comprehensive tests for the interactive Seed Phase loop, candidate review, and seed promotion."""

import io
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import pytest
from typer.testing import CliRunner

from bulkimagecreator.cli import app, set_image_service
from bulkimagecreator.manifest import load_manifest
from bulkimagecreator.models import RunStatus
from bulkimagecreator.seed_phase import launch_viewer, run_seed_phase
from bulkimagecreator.service import MockImageGenerationService

runner = CliRunner()


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    """Fixture creating a temporary valid source image."""
    img_path = tmp_path / "source.png"
    img = Image.new("RGB", (64, 64), color="blue")
    img.save(img_path, format="PNG")
    return img_path


@pytest.fixture(autouse=True)
def configure_mock_service():
    """Ensure MockImageGenerationService is active for all seed phase tests."""
    mock = MockImageGenerationService()
    set_image_service(mock)
    yield mock
    set_image_service(None)


class TestSeedPhaseInteractiveLoop:
    """Tests asserting interactive Seed Phase user stories and menu choices."""

    def test_interactive_prompt_input_when_prompt_omitted(
        self, tmp_path: Path, sample_image: Path, configure_mock_service: MockImageGenerationService
    ) -> None:
        """Assert user is prompted interactively for seed prompt when --prompt is omitted."""
        out_dir = tmp_path / "runs"
        # Provide seed prompt interactively, then accept candidate #1
        user_input = "An enchanted ancient forest\na\n"

        with patch("bulkimagecreator.seed_phase.launch_viewer") as mock_viewer:
            result = runner.invoke(
                app,
                ["run", str(sample_image), "--output-dir", str(out_dir)],
                input=user_input,
            )

        assert result.exit_code == 0
        assert "Enter seed prompt" in result.output
        assert "Generating candidate #1" in result.output
        assert "Accepted candidate #1 as seed image: 00_seed.png" in result.output

        # Verify service received interactive prompt
        assert len(configure_mock_service.call_history) == 1
        assert configure_mock_service.call_history[0]["prompt"] == "An enchanted ancient forest"

        # Verify run folder and files
        run_dirs = list(out_dir.glob("run_*"))
        assert len(run_dirs) == 1
        run_dir = run_dirs[0]

        candidate_file = run_dir / "candidates" / "candidate_01.png"
        assert candidate_file.is_file()

        seed_file = run_dir / "00_seed.png"
        assert seed_file.is_file()
        assert seed_file.read_bytes() == candidate_file.read_bytes()

        # Verify manifest
        manifest = load_manifest(run_dir)
        assert manifest.status == RunStatus.IN_PROGRESS
        assert manifest.seed_phase.seed_prompt == "An enchanted ancient forest"
        assert manifest.seed_phase.accepted_candidate == 1
        assert len(manifest.seed_phase.candidates) == 1
        assert manifest.seed_phase.candidates[0].index == 1
        assert manifest.seed_phase.candidates[0].filename == "candidate_01.png"
        assert manifest.seed_phase.candidates[0].seed_prompt == "An enchanted ancient forest"

    def test_candidate_generation_and_zero_padded_numbering(
        self, tmp_path: Path, sample_image: Path
    ) -> None:
        """Assert candidates are saved with zero-padded numbering (candidate_01.png, candidate_02.png)."""
        out_dir = tmp_path / "runs"
        # Retry once, then accept candidate #2
        user_input = "r\na\n"

        with patch("bulkimagecreator.seed_phase.launch_viewer"):
            result = runner.invoke(
                app,
                [
                    "run",
                    str(sample_image),
                    "--output-dir",
                    str(out_dir),
                    "--prompt",
                    "A crystal cavern",
                ],
                input=user_input,
            )

        assert result.exit_code == 0
        assert "Generating candidate #1" in result.output
        assert "Generating candidate #2" in result.output
        assert "Accepted candidate #2 as seed image: 00_seed.png" in result.output

        run_dir = list(out_dir.glob("run_*"))[0]
        c1 = run_dir / "candidates" / "candidate_01.png"
        c2 = run_dir / "candidates" / "candidate_02.png"
        assert c1.is_file()
        assert c2.is_file()

        # Both candidates must be valid lossless PNGs
        with Image.open(c1) as img1:
            assert img1.format == "PNG"
        with Image.open(c2) as img2:
            assert img2.format == "PNG"

        manifest = load_manifest(run_dir)
        assert len(manifest.seed_phase.candidates) == 2
        assert manifest.seed_phase.candidates[0].filename == "candidate_01.png"
        assert manifest.seed_phase.candidates[1].filename == "candidate_02.png"
        assert manifest.seed_phase.accepted_candidate == 2

    def test_viewer_invocation_enabled_by_default(
        self, tmp_path: Path, sample_image: Path
    ) -> None:
        """Assert OS viewer is invoked by default on macOS."""
        out_dir = tmp_path / "runs"

        with patch("subprocess.run") as mock_subproc, patch("platform.system", return_value="Darwin"):
            result = runner.invoke(
                app,
                [
                    "run",
                    str(sample_image),
                    "--output-dir",
                    str(out_dir),
                    "--prompt",
                    "Viewer test",
                ],
                input="a\n",
            )

        assert result.exit_code == 0
        mock_subproc.assert_called_once()
        args, kwargs = mock_subproc.call_args
        assert args[0][0] == "open"
        assert "candidate_01.png" in args[0][1]

    def test_viewer_invocation_disabled_with_no_open_flag(
        self, tmp_path: Path, sample_image: Path
    ) -> None:
        """Assert OS viewer is NOT invoked when --no-open flag is passed."""
        out_dir = tmp_path / "runs"

        with patch("subprocess.run") as mock_subproc, patch("platform.system", return_value="Darwin"):
            result = runner.invoke(
                app,
                [
                    "run",
                    str(sample_image),
                    "--output-dir",
                    str(out_dir),
                    "--prompt",
                    "No open test",
                    "--no-open",
                ],
                input="a\n",
            )

        assert result.exit_code == 0
        mock_subproc.assert_not_called()

    def test_menu_accept_current_immediately(
        self, tmp_path: Path, sample_image: Path
    ) -> None:
        """Assert menu choice 'a' promotes candidate #1 to 00_seed.png and updates manifest."""
        out_dir = tmp_path / "runs"

        with patch("bulkimagecreator.seed_phase.launch_viewer"):
            result = runner.invoke(
                app,
                [
                    "run",
                    str(sample_image),
                    "--output-dir",
                    str(out_dir),
                    "--prompt",
                    "A vibrant sunset",
                ],
                input="a\n",
            )

        assert result.exit_code == 0
        run_dir = list(out_dir.glob("run_*"))[0]
        seed_path = run_dir / "00_seed.png"
        candidate_path = run_dir / "candidates" / "candidate_01.png"

        assert seed_path.is_file()
        assert seed_path.read_bytes() == candidate_path.read_bytes()

        manifest = load_manifest(run_dir)
        assert manifest.seed_phase.accepted_candidate == 1
        assert manifest.seed_phase.seed_prompt == "A vibrant sunset"
        assert len(manifest.seed_phase.candidates) == 1

    def test_menu_retry_then_pick_candidate_one(
        self, tmp_path: Path, sample_image: Path
    ) -> None:
        """Assert retrying generates candidate 2, then picking candidate 1 promotes candidate 1."""
        out_dir = tmp_path / "runs"
        # Input: retry ('r'), then pick candidate 1 ('p 1')
        user_input = "r\np 1\n"

        with patch("bulkimagecreator.seed_phase.launch_viewer"):
            result = runner.invoke(
                app,
                [
                    "run",
                    str(sample_image),
                    "--output-dir",
                    str(out_dir),
                    "--prompt",
                    "Floating castle",
                ],
                input=user_input,
            )

        assert result.exit_code == 0
        assert "Generating candidate #1" in result.output
        assert "Generating candidate #2" in result.output
        assert "Accepted candidate #1 as seed image: 00_seed.png" in result.output

        run_dir = list(out_dir.glob("run_*"))[0]
        c1 = run_dir / "candidates" / "candidate_01.png"
        c2 = run_dir / "candidates" / "candidate_02.png"
        seed = run_dir / "00_seed.png"

        assert c1.is_file()
        assert c2.is_file()
        assert seed.is_file()

        # Crucial check: seed image bytes must match candidate 1, NOT candidate 2
        assert seed.read_bytes() == c1.read_bytes()
        assert c1.read_bytes() != c2.read_bytes()

        manifest = load_manifest(run_dir)
        assert manifest.seed_phase.accepted_candidate == 1
        assert len(manifest.seed_phase.candidates) == 2

    def test_menu_pick_candidate_with_separate_prompt(
        self, tmp_path: Path, sample_image: Path
    ) -> None:
        """Assert 'p' without inline number prompts for candidate index."""
        out_dir = tmp_path / "runs"
        # Input: retry ('r'), pick ('p'), number ('1')
        user_input = "r\np\n1\n"

        with patch("bulkimagecreator.seed_phase.launch_viewer"):
            result = runner.invoke(
                app,
                [
                    "run",
                    str(sample_image),
                    "--output-dir",
                    str(out_dir),
                    "--prompt",
                    "Separate pick test",
                ],
                input=user_input,
            )

        assert result.exit_code == 0
        assert "Accepted candidate #1 as seed image: 00_seed.png" in result.output
        run_dir = list(out_dir.glob("run_*"))[0]
        manifest = load_manifest(run_dir)
        assert manifest.seed_phase.accepted_candidate == 1

    def test_menu_edit_prompt_updates_prompt_and_generates_next_candidate(
        self, tmp_path: Path, sample_image: Path, configure_mock_service: MockImageGenerationService
    ) -> None:
        """Assert editing prompt generates candidate #2 with new prompt while preserving candidate #1."""
        out_dir = tmp_path / "runs"
        # Input: edit ('e'), new prompt ('Steampunk blimp in clouds'), accept ('a')
        user_input = "e\nSteampunk blimp in clouds\na\n"

        with patch("bulkimagecreator.seed_phase.launch_viewer"):
            result = runner.invoke(
                app,
                [
                    "run",
                    str(sample_image),
                    "--output-dir",
                    str(out_dir),
                    "--prompt",
                    "Cyberpunk car",
                ],
                input=user_input,
            )

        assert result.exit_code == 0
        assert "Generating candidate #1" in result.output
        assert "Prompt: Cyberpunk car" in result.output
        assert "Generating candidate #2" in result.output
        assert "Prompt: Steampunk blimp in clouds" in result.output
        assert "Accepted candidate #2 as seed image: 00_seed.png" in result.output

        # Verify service received both prompts
        assert len(configure_mock_service.call_history) == 2
        assert configure_mock_service.call_history[0]["prompt"] == "Cyberpunk car"
        assert configure_mock_service.call_history[1]["prompt"] == "Steampunk blimp in clouds"

        run_dir = list(out_dir.glob("run_*"))[0]
        c1 = run_dir / "candidates" / "candidate_01.png"
        c2 = run_dir / "candidates" / "candidate_02.png"
        seed = run_dir / "00_seed.png"

        assert c1.is_file()
        assert c2.is_file()
        assert seed.read_bytes() == c2.read_bytes()

        manifest = load_manifest(run_dir)
        assert manifest.seed_phase.accepted_candidate == 2
        assert manifest.seed_phase.seed_prompt == "Steampunk blimp in clouds"
        assert len(manifest.seed_phase.candidates) == 2
        assert manifest.seed_phase.candidates[0].seed_prompt == "Cyberpunk car"
        assert manifest.seed_phase.candidates[1].seed_prompt == "Steampunk blimp in clouds"

    def test_menu_quit_exits_cleanly(
        self, tmp_path: Path, sample_image: Path
    ) -> None:
        """Assert menu choice 'q' exits cleanly with status 0, no 00_seed.png, and candidates preserved."""
        out_dir = tmp_path / "runs"

        with patch("bulkimagecreator.seed_phase.launch_viewer"):
            result = runner.invoke(
                app,
                [
                    "run",
                    str(sample_image),
                    "--output-dir",
                    str(out_dir),
                    "--prompt",
                    "Quit test prompt",
                ],
                input="q\n",
            )

        assert result.exit_code == 0
        assert "Seed phase cancelled" in result.output

        run_dir = list(out_dir.glob("run_*"))[0]
        seed = run_dir / "00_seed.png"
        assert not seed.exists()

        candidate = run_dir / "candidates" / "candidate_01.png"
        assert candidate.is_file()

        manifest = load_manifest(run_dir)
        assert manifest.status == RunStatus.INTERRUPTED
        assert manifest.seed_phase.accepted_candidate is None
        assert len(manifest.seed_phase.candidates) == 1

    def test_menu_invalid_pick_number_reprompts_menu(
        self, tmp_path: Path, sample_image: Path
    ) -> None:
        """Assert invalid candidate number displays error message and reprompts menu."""
        out_dir = tmp_path / "runs"
        # Input: pick invalid candidate 99, then accept current
        user_input = "p 99\na\n"

        with patch("bulkimagecreator.seed_phase.launch_viewer"):
            result = runner.invoke(
                app,
                [
                    "run",
                    str(sample_image),
                    "--output-dir",
                    str(out_dir),
                    "--prompt",
                    "Invalid pick test",
                ],
                input=user_input,
            )

        assert result.exit_code == 0
        assert "Invalid candidate number" in result.output
        assert "Accepted candidate #1 as seed image: 00_seed.png" in result.output

    def test_menu_unknown_option_reprompts(
        self, tmp_path: Path, sample_image: Path
    ) -> None:
        """Assert unknown menu character displays error message and reprompts menu."""
        out_dir = tmp_path / "runs"
        # Input: invalid option 'z', then accept current
        user_input = "z\na\n"

        with patch("bulkimagecreator.seed_phase.launch_viewer"):
            result = runner.invoke(
                app,
                [
                    "run",
                    str(sample_image),
                    "--output-dir",
                    str(out_dir),
                    "--prompt",
                    "Unknown option test",
                ],
                input=user_input,
            )

        assert result.exit_code == 0
        assert "Unknown option" in result.output
        assert "Accepted candidate #1 as seed image: 00_seed.png" in result.output
