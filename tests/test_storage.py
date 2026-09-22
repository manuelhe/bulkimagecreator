"""Unit tests for storage operations."""

from pathlib import Path
from PIL import Image
import pytest

from bulkimagecreator.exceptions import ValidationError
from bulkimagecreator.storage import (
    archive_source_images,
    create_run_directory,
    validate_source_images,
)


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    img_path = tmp_path / "sample.png"
    img = Image.new("RGB", (32, 32), color="blue")
    img.save(img_path, format="PNG")
    return img_path


def test_validate_source_images_valid(sample_image: Path) -> None:
    validated = validate_source_images([sample_image])
    assert len(validated) == 1
    assert validated[0] == sample_image.resolve()


def test_validate_source_images_empty_list() -> None:
    with pytest.raises(ValidationError, match="Must provide between 1 and 4"):
        validate_source_images([])


def test_validate_source_images_too_many(tmp_path: Path, sample_image: Path) -> None:
    paths = [sample_image] * 5
    with pytest.raises(ValidationError, match="Maximum of 4 source images"):
        validate_source_images(paths)


def test_validate_source_images_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="Source image path does not exist"):
        validate_source_images([tmp_path / "missing.png"])


def test_validate_source_images_corrupted_file(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.png"
    bad_file.write_bytes(b"not an image header")
    with pytest.raises(ValidationError, match="File is not a valid or readable image"):
        validate_source_images([bad_file])


def test_create_run_directory_structure(tmp_path: Path) -> None:
    run_id, run_dir = create_run_directory(base_dir=tmp_path)
    assert run_id.startswith("run_")
    assert run_dir.exists()
    assert (run_dir / "sources").is_dir()
    assert (run_dir / "candidates").is_dir()


def test_create_run_directory_custom_id(tmp_path: Path) -> None:
    custom_id = "test_custom_run_01"
    run_id, run_dir = create_run_directory(base_dir=tmp_path, run_id=custom_id)
    assert run_id == custom_id
    assert run_dir == tmp_path / custom_id
    assert run_dir.is_dir()


def test_archive_source_images(tmp_path: Path, sample_image: Path) -> None:
    _, run_dir = create_run_directory(base_dir=tmp_path)
    records = archive_source_images([sample_image], run_dir)
    assert len(records) == 1
    assert records[0].original_path == str(sample_image.resolve())
    assert records[0].archived_path == f"sources/{sample_image.name}"
    archived_file = run_dir / "sources" / sample_image.name
    assert archived_file.exists()
    assert archived_file.read_bytes() == sample_image.read_bytes()
