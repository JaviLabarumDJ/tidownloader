"""Command-line interface for tidownloader."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List

import tidalapi
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from . import __version__
from .api import resolve_url
from .auth import clear_session, login
from .config import Config, QUALITY_OPTIONS, resolve_quality_key
from .downloader import download_track

console = Console()


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tidownloader",
        description="Download music from your Tidal subscription.",
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="Tidal URLs (playlist, album, track, mix, artist).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="./downloads",
        help="Directory where files will be saved (default: ./downloads).",
    )
    parser.add_argument(
        "-q",
        "--quality",
        choices=list(QUALITY_OPTIONS.keys()),
        default="mp3_320",
        help="Audio quality (default: mp3_320).",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch the web dashboard interface.",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Force a new Tidal login (overwrites the saved session).",
    )
    parser.add_argument(
        "--logout",
        action="store_true",
        help="Forget the saved Tidal session.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version and exit.",
    )
    return parser.parse_args(argv)


def _print_track_table(track_count: int, name: str) -> None:
    table = Table(title=f"{name} — {track_count} tracks", show_lines=False)
    console.print(table)


def _select_quality(name: str) -> str:
    return resolve_quality_key(name)


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.version:
        console.print(f"tidownloader {__version__}")
        return 0

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.logout:
        clear_session()
        console.print("[green]Session removed.[/green]")
        return 0

    if args.web:
        from .web.server import main as web_main
        return web_main()

    if not args.urls:
        console.print("[red]error:[/red] at least one URL is required. (Use --web to launch the web dashboard)")
        return 2

    if args.login:
        clear_session()

    try:
        session = login()
    except Exception as exc:
        console.print(f"[red]Authentication failed:[/red] {exc}")
        return 1

    # Merge session quality
    quality = _select_quality(args.quality)

    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cfg = Config(download_path=str(output_dir), quality=quality)

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}[/bold blue]"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    )

    with progress:
        for url in args.urls:
            try:
                tracks, name = resolve_url(session, url)
            except Exception as exc:
                console.print(f"[red]Failed to resolve {url}:[/red] {exc}")
                continue

            if not tracks:
                console.print(f"[yellow]No tracks found at {url}[/yellow]")
                continue

            console.print(f"[bold]{name}[/bold] — {len(tracks)} tracks from {url}")
            for idx, track in enumerate(tracks, start=1):
                task = progress.add_task(
                    f"[{idx}/{len(tracks)}] {track.title}",
                    total=1,
                )

                def _on_progress(completed: int, total: int) -> None:
                    progress.update(
                        task,
                        description=f"[{idx}/{len(tracks)}] {track.title} (segment {completed}/{total})",
                        completed=0,
                        total=total,
                    )

                path = download_track(
                    session, track, cfg, on_progress=_on_progress
                )
                progress.update(task, completed=1, total=1)
                if path:
                    console.print(f"  [green]✓[/green] {path.relative_to(output_dir)}")
                else:
                    console.print(f"  [red]✗[/red] {track.title} — skipped")

    console.print("\n[bold green]Done.[/bold green]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
