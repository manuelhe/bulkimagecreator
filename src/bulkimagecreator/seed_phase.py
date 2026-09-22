"""Interactive Seed Phase loop, candidate review, and seed image promotion."""

from datetime import datetime, timezone
import io
import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Optional
from PIL import Image
from rich.console import Console
from rich.prompt import Prompt

from bulkimagecreator.manifest import save_manifest
from bulkimagecreator.models import (
    CandidateImageRecord,
    RunManifest,
    RunStatus,
    SeedPhaseRecord,
)
from bulkimagecreator.service import ImageGenerationService


def launch_viewer(candidate_path: Path, no_open: bool = False) -> None:
    """Open candidate image in system viewer on macOS unless disabled.

    Args:
        candidate_path: Path to the generated candidate image file.
        no_open: If True, bypass viewer launch.
    """
    if no_open:
        return
    if platform.system() == "Darwin":
        try:
            subprocess.run(["open", str(candidate_path)], check=False)
        except Exception:
            pass


def _promote_candidate(
    accepted_index: int,
    candidate_records: list[CandidateImageRecord],
    candidates_dir: Path,
    run_dir: Path,
    manifest: RunManifest,
    console: Console,
) -> Path:
    """Promote an accepted candidate image to 00_seed.png and persist in manifest."""
    accepted_record = candidate_records[accepted_index - 1]
    selected_candidate_path = candidates_dir / accepted_record.filename
    seed_path = run_dir / "00_seed.png"
    shutil.copy2(selected_candidate_path, seed_path)

    manifest.seed_phase = SeedPhaseRecord(
        seed_prompt=accepted_record.seed_prompt,
        accepted_candidate=accepted_index,
        candidates=list(candidate_records),
    )
    save_manifest(manifest, run_dir)

    console.print(
        f"[bold green]Accepted candidate #{accepted_index} as seed image: 00_seed.png[/bold green]"
    )
    return seed_path


def run_seed_phase(
    run_dir: Path,
    source_images: list[Path],
    manifest: RunManifest,
    service: ImageGenerationService,
    prompt: Optional[str] = None,
    aspect_ratio: str = "1:1",
    model: Optional[str] = None,
    no_open: bool = False,
    console: Optional[Console] = None,
) -> Optional[Path]:
    """Execute the interactive Seed Phase loop.

    Repeatedly generates candidate images using the multimodal image generation service,
    saves them to candidates/candidate_NN.png, opens them in the system viewer,
    and prompts the user to accept, retry, edit prompt, pick a previous candidate, or quit.

    Args:
        run_dir: Directory of the current run.
        source_images: List of source image paths (archived or original).
        manifest: Current RunManifest instance.
        service: Multimodal image generation service.
        prompt: Initial seed prompt (if provided via CLI).
        aspect_ratio: Target aspect ratio.
        model: Model name override.
        no_open: If True, do not launch system viewer.
        console: Optional Rich Console instance.

    Returns:
        Path to promoted 00_seed.png if accepted, or None if aborted/quit.
    """
    if console is None:
        console = Console()

    current_prompt = (prompt or "").strip()
    if not current_prompt:
        try:
            while not current_prompt:
                user_input = Prompt.ask(
                    "[bold cyan]Enter seed prompt[/bold cyan]",
                    console=console,
                )
                if user_input and user_input.strip():
                    current_prompt = user_input.strip()
                else:
                    console.print(
                        "[yellow]Seed prompt cannot be empty. Please enter a prompt.[/yellow]"
                    )
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Seed phase cancelled. Exiting.[/yellow]")
            return None

    candidates_dir = run_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    candidate_records: list[CandidateImageRecord] = list(
        manifest.seed_phase.candidates
    )
    candidate_index = len(candidate_records)

    while True:
        candidate_index += 1
        filename = f"candidate_{candidate_index:02d}.png"
        candidate_path = candidates_dir / filename

        console.print(
            f"\n[bold green]Generating candidate #{candidate_index}...[/bold green]"
        )
        console.print(f"[dim]Prompt: {current_prompt}[/dim]")

        # 1. Generate candidate image bytes via service seam
        image_bytes = service.generate_candidate_image(
            source_images=source_images,
            prompt=current_prompt,
            aspect_ratio=aspect_ratio,
            model=model,
        )

        # 2. Save candidate as lossless PNG
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.save(candidate_path, format="PNG")

        # 3. Create and append candidate record
        record = CandidateImageRecord(
            index=candidate_index,
            filename=filename,
            seed_prompt=current_prompt,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        candidate_records.append(record)

        # 4. Update manifest state with current candidate list
        manifest.seed_phase = SeedPhaseRecord(
            seed_prompt=None,
            accepted_candidate=None,
            candidates=list(candidate_records),
        )
        save_manifest(manifest, run_dir)

        console.print(
            f"[green]Saved candidate #{candidate_index} to candidates/{filename}[/green]"
        )

        # 5. Launch OS viewer (unless disabled)
        launch_viewer(candidate_path, no_open=no_open)

        # 6. Interactive review menu
        while True:
            menu_prompt = (
                "[bold cyan][a][/bold cyan]ccept current | "
                "[bold cyan][p][/bold cyan]ick candidate # | "
                "[bold cyan][e][/bold cyan]dit prompt | "
                "[bold cyan][r][/bold cyan]etry | "
                "[bold cyan][q][/bold cyan]uit"
            )
            try:
                choice = Prompt.ask(menu_prompt, console=console)
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Seed phase cancelled. Exiting.[/yellow]")
                return None

            if not choice:
                continue

            choice_str = choice.strip()
            action = choice_str[0].lower()

            if action == "a":
                # Accept current candidate
                return _promote_candidate(
                    accepted_index=candidate_index,
                    candidate_records=candidate_records,
                    candidates_dir=candidates_dir,
                    run_dir=run_dir,
                    manifest=manifest,
                    console=console,
                )

            elif action == "p":
                # Pick candidate #
                target_idx: Optional[int] = None
                remainder = choice_str[1:].strip()
                if remainder.isdigit():
                    target_idx = int(remainder)
                else:
                    try:
                        pick_input = Prompt.ask(
                            f"Enter candidate number (1..{candidate_index})",
                            console=console,
                        )
                        if pick_input and pick_input.strip().isdigit():
                            target_idx = int(pick_input.strip())
                    except (EOFError, KeyboardInterrupt):
                        console.print("\n[yellow]Seed phase cancelled. Exiting.[/yellow]")
                        manifest.status = RunStatus.INTERRUPTED
                        save_manifest(manifest, run_dir)
                        return None

                if target_idx is None or target_idx < 1 or target_idx > candidate_index:
                    console.print(
                        f"[bold red]Invalid candidate number. Must be between 1 and {candidate_index}.[/bold red]"
                    )
                    continue

                return _promote_candidate(
                    accepted_index=target_idx,
                    candidate_records=candidate_records,
                    candidates_dir=candidates_dir,
                    run_dir=run_dir,
                    manifest=manifest,
                    console=console,
                )

            elif action == "e":
                # Edit prompt
                try:
                    new_prompt = Prompt.ask(
                        "Enter new seed prompt",
                        default=current_prompt,
                        console=console,
                    )
                except (EOFError, KeyboardInterrupt):
                    console.print("\n[yellow]Seed phase cancelled. Exiting.[/yellow]")
                    manifest.status = RunStatus.INTERRUPTED
                    save_manifest(manifest, run_dir)
                    return None

                if new_prompt and new_prompt.strip():
                    current_prompt = new_prompt.strip()
                break  # Exit menu loop to generate next candidate with updated prompt

            elif action == "r":
                # Retry with same prompt
                break  # Exit menu loop to generate next candidate with same prompt

            elif action == "q":
                # Quit cleanly
                console.print("[yellow]Seed phase cancelled. Exiting.[/yellow]")
                manifest.status = RunStatus.INTERRUPTED
                manifest.seed_phase = SeedPhaseRecord(
                    seed_prompt=None,
                    accepted_candidate=None,
                    candidates=list(candidate_records),
                )
                save_manifest(manifest, run_dir)
                return None

            else:
                console.print(
                    f"[bold red]Unknown option '{choice_str}'. Please choose a, p, e, r, or q.[/bold red]"
                )
