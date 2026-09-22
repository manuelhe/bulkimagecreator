"""Run Manifest creation, serialization, and validation."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bulkimagecreator.exceptions import ManifestError
from bulkimagecreator.models import (
    RunConfig,
    RunManifest,
    RunStatus,
    SeedPhaseRecord,
    SourceImageRecord,
)

MANIFEST_FILENAME = "run_manifest.json"


def create_initial_manifest(
    run_id: str,
    config: RunConfig,
    sources: list[SourceImageRecord],
    created_at: Optional[str] = None,
) -> RunManifest:
    """Create an initial Run Manifest in 'in_progress' state.

    Args:
        run_id: Unique identifier for the run.
        config: Configuration parameters for the run.
        sources: List of archived source image records.
        created_at: ISO 8601 timestamp string. If None, uses current UTC time.

    Returns:
        A RunManifest instance populated with initial state.
    """
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()

    return RunManifest(
        run_id=run_id,
        status=RunStatus.IN_PROGRESS,
        created_at=created_at,
        config=config,
        sources=sources,
        seed_phase=SeedPhaseRecord(),
        variations=[],
    )


def save_manifest(manifest: RunManifest, run_dir: Path) -> Path:
    """Atomically write the Run Manifest to disk as JSON.

    Args:
        manifest: The RunManifest to serialize.
        run_dir: Directory where run_manifest.json should be saved.

    Returns:
        Path to the saved run_manifest.json.

    Raises:
        ManifestError: If serialization or writing fails.
    """
    target_path = run_dir / MANIFEST_FILENAME
    temp_path = run_dir / f"{MANIFEST_FILENAME}.tmp"

    try:
        json_data = manifest.model_dump_json(indent=2)
        temp_path.write_text(json_data, encoding="utf-8")
        temp_path.replace(target_path)
    except Exception as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise ManifestError(
            f"Failed to write manifest to {target_path}: {exc}"
        ) from exc

    return target_path


def load_manifest(run_dir: Path) -> RunManifest:
    """Load and validate a Run Manifest from a run directory.

    Args:
        run_dir: Directory containing run_manifest.json.

    Returns:
        Parsed and validated RunManifest.

    Raises:
        ManifestError: If file is missing or contains invalid JSON/schema.
    """
    target_path = run_dir / MANIFEST_FILENAME
    if not target_path.exists():
        raise ManifestError(f"Run manifest not found at {target_path}")

    try:
        content = target_path.read_text(encoding="utf-8")
        return RunManifest.model_validate_json(content)
    except Exception as exc:
        raise ManifestError(
            f"Failed to parse run manifest at {target_path}: {exc}"
        ) from exc
