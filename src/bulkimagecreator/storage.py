"""Storage operations for run directories and source image archiving."""

from datetime import datetime
from pathlib import Path
import shutil
from typing import Optional
from PIL import Image

from bulkimagecreator.exceptions import ValidationError
from bulkimagecreator.models import SourceImageRecord


def validate_source_images(paths: list[Path]) -> list[Path]:
    """Validate 1 to 4 source image paths.

    Args:
        paths: List of file paths to validate.

    Returns:
        List of resolved Path objects for verified image files.

    Raises:
        ValidationError: If count is not between 1 and 4, if any file does not exist,
            or if any file cannot be read as a valid image.
    """
    if not paths or len(paths) < 1:
        raise ValidationError(
            f"Must provide between 1 and 4 source images. Received {len(paths) if paths else 0}."
        )

    if len(paths) > 4:
        raise ValidationError(
            f"Maximum of 4 source images allowed. Received {len(paths)}."
        )

    validated_paths: list[Path] = []
    for path in paths:
        resolved = Path(path).resolve()
        if not resolved.exists() or not resolved.is_file():
            raise ValidationError(f"Source image path does not exist: {path}")

        try:
            with Image.open(resolved) as img:
                img.verify()
        except Exception as exc:
            raise ValidationError(
                f"File is not a valid or readable image: {path} ({exc})"
            )

        validated_paths.append(resolved)

    return validated_paths


def create_run_directory(
    base_dir: Path | str = "runs", run_id: Optional[str] = None
) -> tuple[str, Path]:
    """Create a new timestamped run directory with isolated subfolders.

    Args:
        base_dir: Root directory for runs (defaults to 'runs').
        run_id: Optional explicit run ID. If None, formatted as 'run_YYYYMMDD_HHMMSS'.

    Returns:
        Tuple of (run_id, run_dir_path).
    """
    base_path = Path(base_dir).resolve()
    base_path.mkdir(parents=True, exist_ok=True)

    if run_id is None:
        timestamp = datetime.now().strftime("run_%Y%m%d_%H%M%S")
        candidate_id = timestamp
        candidate_path = base_path / candidate_id
        counter = 1
        while candidate_path.exists():
            candidate_id = f"{timestamp}_{counter:02d}"
            candidate_path = base_path / candidate_id
            counter += 1
        run_id = candidate_id
        run_dir = candidate_path
    else:
        run_dir = base_path / run_id

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "sources").mkdir(parents=True, exist_ok=True)
    (run_dir / "candidates").mkdir(parents=True, exist_ok=True)

    return run_id, run_dir


def archive_source_images(
    source_paths: list[Path], run_dir: Path
) -> list[SourceImageRecord]:
    """Copy source images into the run's sources/ directory for self-contained archiving.

    Args:
        source_paths: Validated paths of the original source images.
        run_dir: Directory of the current run.

    Returns:
        List of SourceImageRecord objects documenting original and archived paths.
    """
    sources_dir = run_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    # Check for colliding filenames across distinct paths
    filenames = [p.name for p in source_paths]
    has_duplicate_names = len(filenames) != len(set(filenames))

    records: list[SourceImageRecord] = []
    for idx, src in enumerate(source_paths, start=1):
        if has_duplicate_names:
            dest_name = f"{idx:02d}_{src.name}"
        else:
            dest_name = src.name

        dest_path = sources_dir / dest_name
        shutil.copy2(src, dest_path)

        records.append(
            SourceImageRecord(
                original_path=str(src.resolve()),
                archived_path=f"sources/{dest_name}",
            )
        )

    return records
