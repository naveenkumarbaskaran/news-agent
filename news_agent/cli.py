"""
CLI for the News Agent.

Usage examples:
  news-agent brief --topics "AI agents, LLM" --output briefing.md
  news-agent brief --topics "SAP, ERP" --feed https://example.com/feed.xml
  news-agent watch --topics "AI agents" --interval 3600
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.syntax import Syntax

from .agent import NewsAgent

console = Console()


# ---------------------------------------------------------------------------
# Shared options
# ---------------------------------------------------------------------------

def _parse_topics(topics_str: str) -> list[str]:
    """Split a comma-separated topics string into a clean list."""
    return [t.strip() for t in topics_str.split(",") if t.strip()]


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(package_name="news-agent-ai")
def cli() -> None:
    """News Agent — AI-powered daily news briefings."""


# ---------------------------------------------------------------------------
# `brief` command
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--topics", "-t",
    required=True,
    help='Comma-separated list of topics, e.g. "AI agents, SAP, LLM"',
)
@click.option(
    "--output", "-o",
    default="briefing.md",
    show_default=True,
    help="Output Markdown file path.",
    type=click.Path(dir_okay=False, writable=True),
)
@click.option(
    "--feed", "-f",
    multiple=True,
    metavar="URL",
    help="Extra RSS/Atom feed URL(s) to include. Repeat for multiple feeds.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Print tool-call progress to stderr.",
)
@click.option(
    "--preview",
    is_flag=True,
    default=False,
    help="Print the first 60 lines of the generated briefing after writing.",
)
def brief(
    topics: str,
    output: str,
    feed: tuple[str, ...],
    verbose: bool,
    preview: bool,
) -> None:
    """
    Generate a one-shot daily news briefing.

    Example:

      news-agent brief --topics "AI agents, SAP, LLM" --output briefing.md
    """
    topic_list = _parse_topics(topics)
    if not topic_list:
        console.print("[red]Error:[/] --topics must include at least one non-empty topic.")
        sys.exit(1)

    console.print(
        Panel(
            f"[bold]Topics:[/] {', '.join(topic_list)}\n"
            f"[bold]Output:[/] {output}\n"
            f"[bold]Extra feeds:[/] {len(feed)}",
            title="[cyan]News Agent — Daily Briefing[/]",
            border_style="cyan",
        )
    )

    agent = NewsAgent()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Researching and writing briefing…", total=None)
        try:
            result_path = agent.run(
                topics=topic_list,
                output_path=output,
                extra_feeds=list(feed) if feed else None,
                verbose=verbose,
            )
        except Exception as exc:  # noqa: BLE001
            progress.stop()
            console.print(f"[red]Error:[/] {exc}")
            sys.exit(1)
        finally:
            progress.remove_task(task)

    file_size = Path(result_path).stat().st_size
    console.print(
        f"[green]✓[/] Briefing written to [bold]{result_path}[/] "
        f"({file_size:,} bytes)"
    )

    if preview:
        lines = Path(result_path).read_text(encoding="utf-8").splitlines()[:60]
        preview_text = "\n".join(lines)
        console.print()
        console.print(Syntax(preview_text, "markdown", theme="monokai", word_wrap=True))


# ---------------------------------------------------------------------------
# `watch` command
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--topics", "-t",
    required=True,
    help='Comma-separated list of topics.',
)
@click.option(
    "--output-dir", "-d",
    default="briefings",
    show_default=True,
    help="Directory to write dated briefing files.",
    type=click.Path(file_okay=False),
)
@click.option(
    "--interval", "-i",
    default=3600,
    show_default=True,
    help="Seconds between briefing runs.",
    type=int,
)
@click.option(
    "--feed", "-f",
    multiple=True,
    metavar="URL",
    help="Extra RSS/Atom feed URL(s) to include.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Print tool-call progress.",
)
def watch(
    topics: str,
    output_dir: str,
    interval: int,
    feed: tuple[str, ...],
    verbose: bool,
) -> None:
    """
    Run briefings on a recurring schedule.

    The briefing file is named by ISO timestamp, e.g.:

      briefings/2025-06-03T09-00.md

    Press Ctrl-C to stop.
    """
    topic_list = _parse_topics(topics)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    console.print(
        Panel(
            f"[bold]Topics:[/] {', '.join(topic_list)}\n"
            f"[bold]Output dir:[/] {out_dir.resolve()}\n"
            f"[bold]Interval:[/] {interval}s ({interval // 60} min)\n"
            "Press [bold]Ctrl-C[/] to stop.",
            title="[cyan]News Agent — Watch Mode[/]",
            border_style="cyan",
        )
    )

    agent = NewsAgent()
    run_number = 0

    try:
        while True:
            run_number += 1
            now = datetime.now(tz=timezone.utc)
            timestamp = now.strftime("%Y-%m-%dT%H-%M")
            output_path = str(out_dir / f"{timestamp}.md")

            console.print(f"\n[cyan]Run #{run_number}[/] — {now.strftime('%Y-%m-%d %H:%M UTC')}")

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task("Researching…", total=None)
                try:
                    result_path = agent.run(
                        topics=topic_list,
                        output_path=output_path,
                        extra_feeds=list(feed) if feed else None,
                        verbose=verbose,
                    )
                    progress.remove_task(task)
                    console.print(f"  [green]✓[/] Saved → [bold]{result_path}[/]")
                except Exception as exc:  # noqa: BLE001
                    progress.remove_task(task)
                    console.print(f"  [red]✗ Error:[/] {exc}")

            next_run = now.replace(second=0, microsecond=0)
            console.print(f"  Next run in {interval}s…")
            time.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    cli()


if __name__ == "__main__":
    main()
