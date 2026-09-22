"""Tests for CLI foundation, argument validation, source archiving, and run manifest."""

import json
from pathlib import Path
from PIL import Image
import pytest
from typer.testing import CliRunner

from bulkimagecreator.cli import app
from bulkimagecreator.manifest import load_manifest
from bulkimagecreator.models import RunStatus

runner = CliRunner()


@pytest.fixture
def make_image():
    """Fixture factory to create temporary valid image files."""

    def _factory(path: Path, color: tuple[int, int, int] = (255, 0, 0)) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (64, 64), color=color)
        img.save(path, format="PNG")
        return path

    return _factory


class TestCliArgumentValidation:
    """Tests asserting argument boundary conditions and file validation."""

    def test_rejection_of_zero_source_images(self) -> None:
        """Assert CLI exits with code 1 and user-friendly error when 0 images are provided."""
        result = runner.invoke(app, ["run"])
        assert result.exit_code == 1
        assert "Must provide between 1 and 4 source images. Received 0." in result.output

    def test_rejection_of_more_than_four_source_images(
        self, tmp_path: Path, make_image
    ) -> None:
        """Assert CLI exits with code 1 when more than 4 images are provided."""
        images = [make_image(tmp_path / f"img_{i}.png") for i in range(5)]
        image_args = [str(p) for p in images]

        result = runner.invoke(app, ["run", *image_args])
        assert result.exit_code == 1
        assert "Maximum of 4 source images allowed. Received 5." in result.output

    def test_rejection_of_non_existent_image_path(
        self, tmp_path: Path, make_image
    ) -> None:
        """Assert CLI exits with code 1 when any specified source image path does not exist."""
        valid_img = make_image(tmp_path / "valid.png")
        ghost_path = tmp_path / "does_not_exist.png"

        result = runner.invoke(app, ["run", str(valid_img), str(ghost_path)])
        assert result.exit_code == 1
        assert "Source image path does not exist" in result.output
        assert "does_not_exist.png" in result.output

    def test_rejection_of_invalid_image_file(self, tmp_path: Path) -> None:
        """Assert CLI exits with code 1 when a file exists but is not a valid image format."""
        corrupt_file = tmp_path / "not_an_image.png"
        corrupt_file.write_text("This is plain text, not an image header.", encoding="utf-8")

        result = runner.invoke(app, ["run", str(corrupt_file)])
        assert result.exit_code == 1
        assert "File is not a valid or readable image" in result.output

    def test_rejection_of_invalid_aspect_ratio(
        self, tmp_path: Path, make_image
    ) -> None:
        """Assert CLI exits with code 1 when an invalid aspect ratio option is supplied."""
        valid_img = make_image(tmp_path / "valid.png")

        result = runner.invoke(
            app, ["run", str(valid_img), "--aspect-ratio", "21:9"]
        )
        assert result.exit_code == 1
        assert "Invalid aspect ratio '21:9'" in result.output


class TestRunCreationAndArchiving:
    """Tests asserting run directory creation, source archiving, and initial manifest."""

    def test_successful_run_initialization(
        self, tmp_path: Path, make_image
    ) -> None:
        """Assert 1 to 4 source images create run folder, copy sources, and write manifest."""
        out_dir = tmp_path / "runs"
        img1 = make_image(tmp_path / "photo1.png", color=(100, 150, 200))
        img2 = make_image(tmp_path / "photo2.png", color=(50, 80, 120))

        result = runner.invoke(
            app,
            [
                "run",
                str(img1),
                str(img2),
                "--output-dir",
                str(out_dir),
                "--model",
                "gemini-2.5-flash-image",
                "--aspect-ratio",
                "16:9",
            ],
        )

        assert result.exit_code == 0
        assert "Run Initialized" in result.output

        # Verify run directory structure
        run_folders = list(out_dir.glob("run_*"))
        assert len(run_folders) == 1
        run_dir = run_folders[0]

        sources_dir = run_dir / "sources"
        assert sources_dir.is_dir()
        archived_files = list(sources_dir.glob("*"))
        assert len(archived_files) == 2

        # Verify archived files exist and match original byte content
        archived_img1 = sources_dir / img1.name
        archived_img2 = sources_dir / img2.name
        assert archived_img1.is_file()
        assert archived_img2.is_file()
        assert archived_img1.read_bytes() == img1.read_bytes()
        assert archived_img2.read_bytes() == img2.read_bytes()

        # Verify candidates directory exists ready for Seed Phase
        assert (run_dir / "candidates").is_dir()

        # Verify run_manifest.json content
        manifest_path = run_dir / "run_manifest.json"
        assert manifest_path.is_file()

        raw_json = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert raw_json["run_id"] == run_dir.name
        assert raw_json["status"] == "in_progress"
        assert raw_json["config"]["model"] == "gemini-2.5-flash-image"
        assert raw_json["config"]["aspect_ratio"] == "16:9"
        assert raw_json["config"]["prompt_template"] == "{prompt}"
        assert raw_json["config"]["delay"] == 1.5
        assert len(raw_json["sources"]) == 2
        assert raw_json["sources"][0]["original_path"] == str(img1.resolve())
        assert raw_json["sources"][0]["archived_path"] == f"sources/{img1.name}"
        assert raw_json["sources"][1]["original_path"] == str(img2.resolve())
        assert raw_json["sources"][1]["archived_path"] == f"sources/{img2.name}"
        assert raw_json["seed_phase"]["seed_prompt"] is None
        assert raw_json["seed_phase"]["accepted_candidate"] is None
        assert raw_json["seed_phase"]["candidates"] == []
        assert raw_json["variations"] == []

        # Verify manifest model parsing
        parsed_manifest = load_manifest(run_dir)
        assert parsed_manifest.status == RunStatus.IN_PROGRESS
        assert parsed_manifest.run_id == run_dir.name
        assert len(parsed_manifest.sources) == 2

    def test_source_archiving_handles_duplicate_filenames(
        self, tmp_path: Path, make_image
    ) -> None:
        """Assert images with identical basenames from different folders are disambiguated."""
        dir_a = tmp_path / "dir_a"
        dir_b = tmp_path / "dir_b"
        img_a = make_image(dir_a / "ref.png", color=(10, 20, 30))
        img_b = make_image(dir_b / "ref.png", color=(40, 50, 60))

        out_dir = tmp_path / "runs"
        result = runner.invoke(
            app,
            ["run", str(img_a), str(img_b), "--output-dir", str(out_dir)],
        )
        assert result.exit_code == 0

        run_dir = list(out_dir.glob("run_*"))[0]
        sources_dir = run_dir / "sources"
        archived_files = sorted(list(sources_dir.glob("*")))
        assert len(archived_files) == 2
        # Disambiguated files
        assert archived_files[0].name == "01_ref.png"
        assert archived_files[1].name == "02_ref.png"
        assert archived_files[0].read_bytes() == img_a.read_bytes()
        assert archived_files[1].read_bytes() == img_b.read_bytes()

        manifest = load_manifest(run_dir)
        assert manifest.config.model == "gemini-3.1-flash-lite-image"
        assert manifest.sources[0].archived_path == "sources/01_ref.png"
        assert manifest.sources[1].archived_path == "sources/02_ref.png"
