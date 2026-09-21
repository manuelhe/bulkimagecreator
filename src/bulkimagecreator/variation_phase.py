"""Variation Phase batch traversal, WebP encoding, and live progress."""

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

from bulkimagecreator.exceptions import ValidationError
from bulkimagecreator.manifest import save_manifest
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
    delay: float = 0.0,
    console: Optional[Console] = None,
) -> list[Path]:
    """Execute the automated Variation Phase batch traversal.

    Iterates through variation prompts using exclusively 00_seed.png as the visual ancestor (ADR 0001),
    formats each prompt with prompt_template, generates variations, encodes them in WebP format (ADR 0002)
    with sequential zero-padded naming (01_variation.webp, 02_variation.webp), updates run_manifest.json
    atomically after each item, and displays a live Rich progress bar and summary table.

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
        delay: Inter-request pacing delay in seconds.
        console: Optional Rich Console instance.

    Returns:
        List of paths to generated WebP variation files.

    Raises:
        ValidationError: If seed image is missing or prompt template is invalid.
    """
    if console is None:
        console = Console()

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
        return []

    saved_paths: list[Path] = []
    success_count = 0
    existing_count = len(manifest.variations)

    console.print(
        f"\n[bold cyan]Starting Variation Phase: {len(prompts)} prompt(s) to process[/bold cyan]"
    )

    # 2. Live progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("({task.completed}/{task.total})"),
        TextColumn("[bold green]Success: {task.fields[successes]}[/bold green]"),
        console=console,
    ) as progress:
        task_id = progress.add_task(
            "Generating variations",
            total=len(prompts),
            successes=0,
        )

        for i, raw_prompt in enumerate(prompts, start=1):
            var_index = existing_count + i

            if delay > 0 and i > 1:
                time.sleep(delay)

            formatted_prompt = format_variation_prompt(raw_prompt, prompt_template)

            # Call service passing exclusively seed image (ADR 0001)
            image_bytes = service.generate_variation_image(
                seed_image=seed_image_path,
                prompt=formatted_prompt,
                aspect_ratio=aspect_ratio,
                model=model,
            )

            # Convert to WebP and save sequentially (ADR 0002)
            filename = f"{var_index:02d}_variation.webp"
            variation_path = run_dir / filename

            with Image.open(io.BytesIO(image_bytes)) as img:
                img.save(variation_path, format="WEBP")

            saved_paths.append(variation_path)
            success_count += 1

            # Atomically update manifest after each variation
            record = VariationRecord(
                index=var_index,
                prompt=raw_prompt,
                expanded_prompt=formatted_prompt,
                status=VariationExecutionStatus.SUCCESS,
                output_filename=filename,
            )
            manifest.variations.append(record)
            save_manifest(manifest, run_dir)

            progress.update(task_id, advance=1, successes=success_count)

    # 3. Mark run as COMPLETED and persist manifest
    manifest.status = RunStatus.COMPLETED
    save_manifest(manifest, run_dir)

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
    summary_table.add_row("Output Directory", str(run_dir))
    summary_table.add_row("Status", manifest.status.value)

    console.print(summary_table)

    return saved_paths
