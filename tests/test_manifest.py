"""Unit tests for run manifest creation, saving, and loading."""

from pathlib import Path
import pytest

from bulkimagecreator.exceptions import ManifestError
from bulkimagecreator.manifest import (
    create_initial_manifest,
    load_manifest,
    save_manifest,
)
from bulkimagecreator.models import RunConfig, RunStatus, SourceImageRecord


def test_create_initial_manifest() -> None:
    config = RunConfig(model="gemini-test", aspect_ratio="16:9", prompt_template="{prompt}")
    sources = [
        SourceImageRecord(original_path="/path/to/img.png", archived_path="sources/img.png")
    ]
    manifest = create_initial_manifest(run_id="run_123", config=config, sources=sources)

    assert manifest.run_id == "run_123"
    assert manifest.status == RunStatus.IN_PROGRESS
    assert manifest.config.model == "gemini-test"
    assert manifest.config.aspect_ratio == "16:9"
    assert len(manifest.sources) == 1
    assert manifest.seed_phase.seed_prompt is None
    assert manifest.seed_phase.accepted_candidate is None
    assert manifest.seed_phase.candidates == []
    assert manifest.variations == []


def test_save_and_load_manifest(tmp_path: Path) -> None:
    config = RunConfig()
    sources = [
        SourceImageRecord(original_path="/orig/a.png", archived_path="sources/a.png")
    ]
    manifest = create_initial_manifest(run_id="run_test", config=config, sources=sources)

    saved_path = save_manifest(manifest, tmp_path)
    assert saved_path == tmp_path / "run_manifest.json"
    assert saved_path.exists()

    loaded = load_manifest(tmp_path)
    assert loaded.run_id == "run_test"
    assert loaded.status == RunStatus.IN_PROGRESS
    assert loaded.sources[0].archived_path == "sources/a.png"


def test_load_manifest_not_found(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="not found"):
        load_manifest(tmp_path)


def test_load_manifest_invalid_json(tmp_path: Path) -> None:
    bad_manifest = tmp_path / "run_manifest.json"
    bad_manifest.write_text("not json content", encoding="utf-8")
    with pytest.raises(ManifestError, match="Failed to parse"):
        load_manifest(tmp_path)
