"""Domain entities and schemas for Bulk Image Creator.

Adheres strictly to the ubiquitous language defined in CONTEXT.md and
the schema defined in docs/spec/0001-bulk-image-creator.md.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    """Lifecycle state of a Run."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


class AspectRatio(str, Enum):
    """Supported aspect ratios for generated images."""

    SQUARE = "1:1"
    PORTRAIT_3_4 = "3:4"
    LANDSCAPE_4_3 = "4:3"
    PORTRAIT_9_16 = "9:16"
    LANDSCAPE_16_9 = "16:9"


class RunConfig(BaseModel):
    """Configuration parameters for a Run."""

    model: str = "gemini-3.1-flash-lite-image"
    aspect_ratio: str = "1:1"
    prompt_template: str = "{prompt}"
    delay: float = 1.5


class SourceImageRecord(BaseModel):
    """Record of an archived Source Image."""

    original_path: str
    archived_path: str


class CandidateImageRecord(BaseModel):
    """Record of a Candidate Image generated during the Seed Phase."""

    index: int
    filename: str
    seed_prompt: str
    created_at: str


class SeedPhaseRecord(BaseModel):
    """Execution state and history of the Seed Phase."""

    seed_prompt: Optional[str] = None
    accepted_candidate: Optional[int] = None
    candidates: list[CandidateImageRecord] = Field(default_factory=list)


class VariationExecutionStatus(str, Enum):
    """Execution status of a Variation Prompt traversal item."""

    PENDING = "pending"
    SUCCESS = "success"
    SKIPPED = "skipped"


class VariationRecord(BaseModel):
    """Record of an individual Variation iteration during the Variation Phase."""

    index: int
    prompt: str
    expanded_prompt: str
    status: VariationExecutionStatus = VariationExecutionStatus.PENDING
    output_filename: Optional[str] = None
    error: Optional[str] = None
    is_transient: bool = False


class RunManifest(BaseModel):
    """Run Manifest documenting run configuration, source images, candidate history, and variations."""

    run_id: str
    status: RunStatus = RunStatus.IN_PROGRESS
    created_at: str
    config: RunConfig = Field(default_factory=RunConfig)
    sources: list[SourceImageRecord] = Field(default_factory=list)
    seed_phase: SeedPhaseRecord = Field(default_factory=SeedPhaseRecord)
    variations: list[VariationRecord] = Field(default_factory=list)
