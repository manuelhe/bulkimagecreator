"""Command-line interface for Bulk Image Creator."""

from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.table import Table
import typer

from bulkimagecreator.exceptions import ValidationError
from bulkimagecreator.manifest import create_initial_manifest, save_manifest
from bulkimagecreator.models import AspectRatio, RunConfig
from bulkimagecreator.storage import (
    archive_source_images,
    create_run_directory,
    validate_source_images,
)

# Load environment variables from .env if present
load_dotenv()

app = typer.Typer(
    name="bulkimagecreator",
    help="Bulk Image Creator CLI: transforms reference images into a curated seed image, then generates a batch of image variations.",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def main() -> None:
    """Bulk Image Creator command line interface."""
    pass


@app.command(name="run")
def run_command(
    source_images: Optional[list[Path]] = typer.Argument(
        None,
        help="1 to 4 source image paths providing reference context.",
        show_default=False,
    ),
    output_dir: Path = typer.Option(
        Path("runs"),
        "--output-dir",
        "-o",
        help="Directory where timestamped run folders will be created.",
    ),
    prompt: Optional[str] = typer.Option(
        None,
        "--prompt",
        "-p",
        help="Seed prompt to generate candidate seed images.",
    ),
    prompt_template: str = typer.Option(
        "{prompt}",
        "--prompt-template",
        help="Template pattern containing {prompt} applied during variation phase.",
    ),
    aspect_ratio: str = typer.Option(
        "1:1",
        "--aspect-ratio",
        "-a",
        help="Target aspect ratio (1:1, 3:4, 4:3, 9:16, 16:9).",
    ),
    model: str = typer.Option(
        "gemini-2.5-flash-image",
        "--model",
        "-m",
        help="Multimodal image generation model name.",
    ),
    delay: float = typer.Option(
        1.5,
        "--delay",
        "-d",
        help="Inter-request pacing delay in seconds.",
    ),
    no_open: bool = typer.Option(
        False,
        "--no-open",
        help="Disable automatic opening of generated images in OS viewer.",
    ),
) -> None:
    """Initialize a new run with 1 to 4 source images and start generation."""
    # 1. Validate argument count boundaries
    if not source_images or len(source_images) < 1:
        console.print(
            "[bold red]Error:[/bold red] Must provide between 1 and 4 source images. Received 0."
        )
        raise typer.Exit(code=1)

    if len(source_images) > 4:
        console.print(
            f"[bold red]Error:[/bold red] Maximum of 4 source images allowed. Received {len(source_images)}."
        )
        raise typer.Exit(code=1)

    # 2. Validate aspect ratio option
    valid_aspect_ratios = [ar.value for ar in AspectRatio]
    if aspect_ratio not in valid_aspect_ratios:
        console.print(
            f"[bold red]Error:[/bold red] Invalid aspect ratio '{aspect_ratio}'. Must be one of: {', '.join(valid_aspect_ratios)}."
        )
        raise typer.Exit(code=1)

    # 3. Validate source image files (existence and Pillow readability)
    try:
        validated_sources = validate_source_images(source_images)
    except ValidationError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)

    # 4. Initialize run directory and archive source images
    try:
        run_id, run_dir = create_run_directory(base_dir=output_dir)
        archived_sources = archive_source_images(validated_sources, run_dir)

        # 5. Build and save initial Run Manifest
        config = RunConfig(
            model=model,
            aspect_ratio=aspect_ratio,
            prompt_template=prompt_template,
            delay=delay,
        )
        manifest = create_initial_manifest(
            run_id=run_id,
            config=config,
            sources=archived_sources,
        )
        manifest_path = save_manifest(manifest, run_dir)
    except Exception as exc:
        console.print(f"[bold red]Error:[/bold red] Failed to initialize run: {exc}")
        raise typer.Exit(code=1)

    # 6. Render Rich terminal summary table
    table = Table(
        title=f"Bulk Image Creator - Run Initialized: {run_id}",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("Property", style="bold white", width=22)
    table.add_column("Value", style="green")

    table.add_row("Run ID", run_id)
    table.add_row("Run Directory", str(run_dir))
    table.add_row("Status", manifest.status.value)
    table.add_row("Model", config.model)
    table.add_row("Aspect Ratio", config.aspect_ratio)
    table.add_row("Prompt Template", config.prompt_template)
    table.add_row("Inter-request Delay", f"{config.delay}s")
    table.add_row("Manifest File", str(manifest_path))

    for idx, src in enumerate(archived_sources, start=1):
        table.add_row(
            f"Source Image #{idx}",
            f"{src.original_path}\n↳ archived: {src.archived_path}",
        )

    console.print(table)


if __name__ == "__main__":
    app()
