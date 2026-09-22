"""Variation Phase batch traversal, WebP encoding, and live progress."""

from collections.abc import Callable
import io
from pathlib import Path
import time
from typing import Optional
from PIL import Image
from rich import box
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.prompt import Prompt
from rich.table import Table

from bulkimagecreator.exceptions import (
    NonTransientGenerationError,
    SafetyBlockError,
    TransientGenerationError,
    ValidationError,
)
from bulkimagecreator.manifest import load_manifest, save_manifest
from bulkimagecreator.models import (
    RunManifest,
    RunStatus,
    VariationExecutionStatus,
    VariationRecord,
)
from bulkimagecreator.service import ImageGenerationService


def load_variation_prompts(
    prompts_file: Optional[Path] = None,
    prompt_inputs: Optional[list[str]] = None,
    console: Optional[Console] = None,
) -> list[str]:
    """Load and sanitize variation prompts from a file, direct list, or interactive input.

    Strips empty lines, leading/trailing whitespace, and comment lines starting with '#'.

    Args:
        prompts_file: Path to text file containing variation prompts.
        prompt_inputs: Direct list of raw prompt strings.
        console: Optional Rich Console instance for interactive prompts.

    Returns:
        List of non-empty, sanitized variation prompt strings.

    Raises:
        ValidationError: If prompts_file does not exist.
    """
    if prompt_inputs is not None:
        return [
            line.strip()
            for line in prompt_inputs
            if line.strip() and not line.strip().startswith("#")
        ]

    if prompts_file is not None:
        path = Path(prompts_file)
        if not path.is_file():
            raise ValidationError(f"Prompts file not found: {prompts_file}")
        content = path.read_text(encoding="utf-8")
        return [
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    if console is None:
        console = Console()

    try:
        console.print("\n[bold cyan]Variation Phase - Prompts Configuration[/bold cyan]")
        file_path_str = Prompt.ask(
            "Enter path to prompts file (or press Enter to enter prompts interactively)",
            default="",
            console=console,
        )
        if file_path_str.strip():
            file_path = Path(file_path_str.strip())
            if not file_path.is_file():
                console.print(f"[bold red]File not found:[/bold red] {file_path}")
                raise ValidationError(f"Prompts file not found: {file_path}")
            return load_variation_prompts(prompts_file=file_path, console=console)

        console.print(
            "[dim]Enter variation prompts (one per line, press Enter on an empty line to finish):[/dim]"
        )
        prompts: list[str] = []
        while True:
            line = Prompt.ask(
                f"Variation prompt #{len(prompts) + 1}",
                default="",
                console=console,
            )
            if not line or not line.strip():
                break
            stripped = line.strip()
            if not stripped.startswith("#"):
                prompts.append(stripped)
        return prompts
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]Variation phase cancelled. Exiting.[/yellow]")
        return []


def format_variation_prompt(raw_prompt: str, template: str = "{prompt}") -> str:
    """Format raw variation prompt with prompt template.

    Args:
        raw_prompt: Raw variation prompt text.
        template: Template string containing '{prompt}' placeholder.

    Returns:
        Formatted variation prompt.

    Raises:
        ValidationError: If '{prompt}' placeholder is missing from template.
    """
    if "{prompt}" not in template:
        raise ValidationError(
            f"Prompt template must contain '{{prompt}}' placeholder, got: '{template}'"
        )
    return template.replace("{prompt}", raw_prompt.strip())


def _generate_and_save_variation(
    record: VariationRecord,
    seed_image_path: Path,
    run_dir: Path,
    manifest: RunManifest,
    service: ImageGenerationService,
    aspect_ratio: str,
    model: Optional[str],
    max_retries: int,
    initial_backoff: float,
    sleeper: Callable[[float], None],
    console: Console,
) -> Optional[Path]:
    """Execute generation for a single variation record, retry transient errors, save WebP, and update manifest."""
    var_index = record.index
    raw_prompt = record.prompt
    formatted_prompt = record.expanded_prompt

    image_bytes: Optional[bytes] = None
    skip_reason: Optional[str] = None
    is_transient = False

    attempt = 0
    while attempt <= max_retries:
        try:
            image_bytes = service.generate_variation_image(
                seed_image=seed_image_path,
                prompt=formatted_prompt,
                aspect_ratio=aspect_ratio,
                model=model,
            )
            break
        except TransientGenerationError as exc:
            attempt += 1
            if attempt <= max_retries:
                backoff = initial_backoff * (2 ** (attempt - 1))
                console.print(
                    f"[yellow]Transient error for prompt #{var_index} ('{raw_prompt}'): {exc}. "
                    f"Retrying in {backoff:.1f}s (retry {attempt}/{max_retries})...[/yellow]"
                )
                sleeper(backoff)
            else:
                skip_reason = f"Transient error retries exhausted: {exc}"
                is_transient = True
                console.print(
                    f"[bold red]Transient error retries exhausted for prompt #{var_index}: {exc}. Skipping.[/bold red]"
                )
        except (SafetyBlockError, NonTransientGenerationError) as exc:
            skip_reason = str(exc)
            is_transient = False
            console.print(
                f"[bold yellow]Prompt #{var_index} skipped due to safety/policy block: {exc}[/bold yellow]"
            )
            break
        except Exception as exc:
            skip_reason = str(exc)
            is_transient = False
            console.print(
                f"[bold red]Prompt #{var_index} failed with unexpected error: {exc}. Skipping.[/bold red]"
            )
            break

    if image_bytes is not None:
        filename = f"{var_index:02d}_variation.webp"
        variation_path = run_dir / filename

        with Image.open(io.BytesIO(image_bytes)) as img:
            img.save(variation_path, format="WEBP")

        record.status = VariationExecutionStatus.SUCCESS
        record.output_filename = filename
        record.error = None
        record.is_transient = False
        save_manifest(manifest, run_dir)
        return variation_path
    else:
        record.status = VariationExecutionStatus.SKIPPED
        record.output_filename = None
        record.error = skip_reason or "Unknown error"
        record.is_transient = is_transient
        save_manifest(manifest, run_dir)
        return None


def run_variation_phase(
    run_dir: Path,
    manifest: RunManifest,
    service: ImageGenerationService,
    seed_image_path: Optional[Path] = None,
    prompts_file: Optional[Path] = None,
    prompt_inputs: Optional[list[str]] = None,
    prompt_template: str = "{prompt}",
    aspect_ratio: str = "1:1",
    model: Optional[str] = None,
    delay: float = 1.5,
    max_retries: int = 2,
    initial_backoff: float = 1.0,
    sleeper: Optional[Callable[[float], None]] = None,
    console: Optional[Console] = None,
) -> list[Path]:
    """Execute the automated Variation Phase batch traversal.

    Iterates through variation prompts using exclusively 00_seed.png as the visual ancestor (ADR 0001),
    formats each prompt with prompt_template, generates variations, encodes them in WebP format (ADR 0002)
    with sequential zero-padded naming (01_variation.webp, 02_variation.webp), updates run_manifest.json
    atomically after each item, retries transient errors with exponential backoff, skips non-transient
    and safety errors without crashing, paces requests with delay, and displays a live Rich progress bar
    and summary table.

    Args:
        run_dir: Directory of the current run.
        manifest: Current RunManifest instance.
        service: Multimodal image generation service.
        seed_image_path: Path to accepted 00_seed.png (defaults to run_dir / "00_seed.png").
        prompts_file: Optional path to prompts text file.
        prompt_inputs: Optional list of raw prompt strings.
        prompt_template: Formatting pattern containing '{prompt}'.
        aspect_ratio: Target aspect ratio.
        model: Model override name.
        delay: Inter-request pacing delay in seconds (default 1.5s).
        max_retries: Maximum number of retries for transient errors (default 2).
        initial_backoff: Initial backoff delay in seconds for retries (default 1.0s).
        sleeper: Callable for delays/sleeps (defaults to time.sleep).
        console: Optional Rich Console instance.

    Returns:
        List of paths to generated WebP variation files.

    Raises:
        ValidationError: If seed image is missing or prompt template is invalid.
    """
    if console is None:
        console = Console()

    if sleeper is None:
        sleeper = time.sleep

    if seed_image_path is None:
        seed_image_path = run_dir / "00_seed.png"

    if not seed_image_path.is_file():
        raise ValidationError(f"Seed image not found at {seed_image_path}")

    # Validate template early
    format_variation_prompt("", template=prompt_template)

    # 1. Load variation prompts
    prompts = load_variation_prompts(
        prompts_file=prompts_file,
        prompt_inputs=prompt_inputs,
        console=console,
    )

    if not prompts:
        console.print(
            "[yellow]No variation prompts provided. Variation phase completed.[/yellow]"
        )

        summary_table = Table(
            title="Variation Phase - Execution Summary",
            box=box.ROUNDED,
            header_style="bold cyan",
        )
        summary_table.add_column("Metric", style="bold white", width=22)
        summary_table.add_column("Value", style="green")
        summary_table.add_row("Run Directory", str(run_dir))
        summary_table.add_row("Total Prompts", "0")
        summary_table.add_row("Successful Images", "0")
        summary_table.add_row("Skipped Prompts", "0")
        summary_table.add_row("Output Directory", str(run_dir))
        summary_table.add_row("Status", manifest.status.value)
        console.print(summary_table)
        return []

    saved_paths: list[Path] = []
    success_count = 0
    skipped_count = 0
    existing_count = len(manifest.variations)

    console.print(
        f"\n[bold cyan]Starting Variation Phase: {len(prompts)} prompt(s) to process[/bold cyan]"
    )

    # Initialize pending records for prompts not yet in manifest
    for i, raw_prompt in enumerate(prompts, start=1):
        var_index = existing_count + i
        formatted_prompt = format_variation_prompt(raw_prompt, prompt_template)
        record = VariationRecord(
            index=var_index,
            prompt=raw_prompt,
            expanded_prompt=formatted_prompt,
            status=VariationExecutionStatus.PENDING,
        )
        manifest.variations.append(record)
    save_manifest(manifest, run_dir)

    # 2. Live progress bar
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("({task.completed}/{task.total})"),
            TextColumn("[bold green]Success: {task.fields[successes]}[/bold green]"),
            TextColumn("[bold yellow]Skipped: {task.fields[skipped]}[/bold yellow]"),
            console=console,
        ) as progress:
            task_id = progress.add_task(
                "Generating variations",
                total=len(prompts),
                successes=0,
                skipped=0,
            )

            for i, raw_prompt in enumerate(prompts, start=1):
                var_index = existing_count + i
                record = manifest.variations[var_index - 1]

                variation_path = _generate_and_save_variation(
                    record=record,
                    seed_image_path=seed_image_path,
                    run_dir=run_dir,
                    manifest=manifest,
                    service=service,
                    aspect_ratio=aspect_ratio,
                    model=model,
                    max_retries=max_retries,
                    initial_backoff=initial_backoff,
                    sleeper=sleeper,
                    console=console,
                )

                if variation_path is not None:
                    saved_paths.append(variation_path)
                    success_count += 1
                else:
                    skipped_count += 1

                progress.update(
                    task_id,
                    advance=1,
                    successes=success_count,
                    skipped=skipped_count,
                )

                # Pacing delay between requests (skip if delay <= 0 or if last item)
                if delay > 0 and i < len(prompts):
                    sleeper(delay)

        # 3. Mark run as COMPLETED and persist manifest
        manifest.status = RunStatus.COMPLETED
        save_manifest(manifest, run_dir)
    except KeyboardInterrupt:
        manifest.status = RunStatus.INTERRUPTED
        save_manifest(manifest, run_dir)
        console.print("\n[yellow]Run interrupted by user. Saved status as 'interrupted'.[/yellow]")
        raise

    # 4. Display terminal summary table
    summary_table = Table(
        title="Variation Phase - Execution Summary",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    summary_table.add_column("Metric", style="bold white", width=22)
    summary_table.add_column("Value", style="green")

    summary_table.add_row("Run Directory", str(run_dir))
    summary_table.add_row("Total Prompts", str(len(prompts)))
    summary_table.add_row("Successful Images", str(success_count))
    summary_table.add_row("Skipped Prompts", str(skipped_count))
    summary_table.add_row("Output Directory", str(run_dir))
    summary_table.add_row("Status", manifest.status.value)

    console.print(summary_table)

    return saved_paths


def is_transient_failure(record: VariationRecord) -> bool:
    """Return True if record was skipped due to a transient failure that can be retried."""
    if record.status != VariationExecutionStatus.SKIPPED:
        return False
    if getattr(record, "is_transient", False):
        return True
    if record.error and "Transient error" in record.error:
        return True
    return False


def resume_variation_phase(
    run_dir: Path,
    service: ImageGenerationService,
    prompts_file: Optional[Path] = None,
    delay: Optional[float] = None,
    model: Optional[str] = None,
    max_retries: int = 2,
    initial_backoff: float = 1.0,
    sleeper: Optional[Callable[[float], None]] = None,
    console: Optional[Console] = None,
) -> list[Path]:
    """Resume an interrupted or partially completed variation phase run.

    Validates run directory existence, valid manifest JSON, and presence of 00_seed.png.
    Inspects run_manifest.json to identify unprocessed (pending) and transiently failed variation prompts.
    Preserves all already generated variation images without overwriting or re-indexing them.
    Traverses remaining prompts with progress bar and pacing delay.
    Updates run_manifest.json status from interrupted to completed when all prompts are traversed.

    Args:
        run_dir: Directory of the run to resume.
        service: Multimodal image generation service.
        prompts_file: Optional prompts file if resuming with an external prompt list.
        delay: Inter-request pacing delay in seconds (defaults to manifest run config if not specified).
        model: Optional model override.
        max_retries: Maximum number of retries for transient errors (default 2).
        initial_backoff: Initial backoff delay in seconds for retries (default 1.0s).
        sleeper: Callable for delays/sleeps (defaults to time.sleep).
        console: Optional Rich Console instance.

    Returns:
        List of paths to newly generated or completed WebP variation files.

    Raises:
        ValidationError: If run directory, manifest, or seed image is invalid or missing.
    """
    if console is None:
        console = Console()

    if sleeper is None:
        sleeper = time.sleep

    # 1. Validate run directory
    run_dir = Path(run_dir)
    if not run_dir.exists() or not run_dir.is_dir():
        raise ValidationError(f"Run directory not found: {run_dir}")

    # 2. Validate manifest file existence and validity
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        raise ValidationError(f"Run manifest not found in: {run_dir}")

    manifest = load_manifest(run_dir)

    # 3. Validate seed image existence
    seed_image_path = run_dir / "00_seed.png"
    if not seed_image_path.is_file():
        raise ValidationError(f"Seed image (00_seed.png) not found in: {run_dir}")

    # 4. Resolve configuration
    actual_delay = delay if delay is not None else manifest.config.delay
    actual_model = model if model is not None else manifest.config.model
    prompt_template = manifest.config.prompt_template
    aspect_ratio = manifest.config.aspect_ratio

    # 5. If prompts_file provided, reconcile with manifest variations
    if prompts_file is not None:
        file_prompts = load_variation_prompts(prompts_file=prompts_file, console=console)
        existing_prompts_count = len(manifest.variations)
        if len(file_prompts) > existing_prompts_count:
            extra_prompts = file_prompts[existing_prompts_count:]
            start_index = max([v.index for v in manifest.variations], default=0) + 1
            for offset, p in enumerate(extra_prompts):
                formatted = format_variation_prompt(p, prompt_template)
                manifest.variations.append(
                    VariationRecord(
                        index=start_index + offset,
                        prompt=p,
                        expanded_prompt=formatted,
                        status=VariationExecutionStatus.PENDING,
                    )
                )
            save_manifest(manifest, run_dir)

    # 6. Identify variation records needing execution:
    # Pending items or items that suffered transient failures
    records_to_process: list[VariationRecord] = []
    preserved_paths: list[Path] = []

    for record in manifest.variations:
        if record.status == VariationExecutionStatus.SUCCESS and record.output_filename:
            file_path = run_dir / record.output_filename
            if file_path.is_file():
                preserved_paths.append(file_path)
                continue
        if record.status == VariationExecutionStatus.PENDING or is_transient_failure(record):
            records_to_process.append(record)

    if not records_to_process:
        console.print("[green]All variation prompts in run are already completed. Nothing to resume.[/green]")
        manifest.status = RunStatus.COMPLETED
        save_manifest(manifest, run_dir)
        return preserved_paths

    console.print(
        f"\n[bold cyan]Resuming Variation Phase for run '{manifest.run_id}': {len(records_to_process)} prompt(s) to process ({len(preserved_paths)} already completed)[/bold cyan]"
    )

    manifest.status = RunStatus.IN_PROGRESS
    save_manifest(manifest, run_dir)

    new_saved_paths: list[Path] = []
    success_count = 0
    skipped_count = 0

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("({task.completed}/{task.total})"),
            TextColumn("[bold green]Success: {task.fields[successes]}[/bold green]"),
            TextColumn("[bold yellow]Skipped: {task.fields[skipped]}[/bold yellow]"),
            console=console,
        ) as progress:
            task_id = progress.add_task(
                "Resuming variations",
                total=len(records_to_process),
                successes=0,
                skipped=0,
            )

            for i, record in enumerate(records_to_process, start=1):
                variation_path = _generate_and_save_variation(
                    record=record,
                    seed_image_path=seed_image_path,
                    run_dir=run_dir,
                    manifest=manifest,
                    service=service,
                    aspect_ratio=aspect_ratio,
                    model=actual_model,
                    max_retries=max_retries,
                    initial_backoff=initial_backoff,
                    sleeper=sleeper,
                    console=console,
                )

                if variation_path is not None:
                    new_saved_paths.append(variation_path)
                    success_count += 1
                else:
                    skipped_count += 1

                progress.update(
                    task_id,
                    advance=1,
                    successes=success_count,
                    skipped=skipped_count,
                )

                if actual_delay > 0 and i < len(records_to_process):
                    sleeper(actual_delay)

        manifest.status = RunStatus.COMPLETED
        save_manifest(manifest, run_dir)
    except KeyboardInterrupt:
        manifest.status = RunStatus.INTERRUPTED
        save_manifest(manifest, run_dir)
        console.print("\n[yellow]Resume interrupted by user. Saved status as 'interrupted'.[/yellow]")
        raise

    summary_table = Table(
        title="Variation Phase - Resume Summary",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    summary_table.add_column("Metric", style="bold white", width=22)
    summary_table.add_column("Value", style="green")

    summary_table.add_row("Run Directory", str(run_dir))
    summary_table.add_row("Total Variations", str(len(manifest.variations)))
    summary_table.add_row("Previously Completed", str(len(preserved_paths)))
    summary_table.add_row("Resumed / Executed", str(len(records_to_process)))
    summary_table.add_row("Newly Successful", str(success_count))
    summary_table.add_row("Skipped Prompts", str(skipped_count))
    summary_table.add_row("Status", manifest.status.value)

    console.print(summary_table)

    return preserved_paths + new_saved_paths
