"""crawler-core CLI — list registered crawlers, run one, inspect results.

Commands:
    crawler-core list                 show every registered crawler
    crawler-core run <source_id>      run one, snapshot to data/<id>/<date>.json
    crawler-core describe <source_id> structured self-description of one crawler
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

# Importing sources triggers auto-registration via @register on every module.
import crawler_core.sources  # noqa: F401
from crawler_core.base import all_sources, get_crawler
from crawler_core.models import CrawlResult, Record


app = typer.Typer(no_args_is_help=True, add_completion=False)
out = Console()
err = Console(stderr=True)


@app.callback()
def _root() -> None:
    """Deterministic per-site crawlers with a plug-and-play registry."""


@app.command("list")
def list_cmd(
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show every registered crawler."""
    sources = all_sources()
    if not sources:
        err.print("[red]no crawlers registered[/red]")
        raise typer.Exit(1)

    if as_json:
        payload = [get_crawler(sid)().describe() for sid in sources]
        out.print_json(json.dumps(payload))
        return

    table = Table(show_edge=False)
    table.add_column("source_id", style="cyan")
    table.add_column("class")
    table.add_column("root_url")
    for source_id in sources:
        cls = get_crawler(source_id)
        table.add_row(source_id, cls.__name__, cls.root_url)
    out.print(table)


@app.command("run")
def run_cmd(
    source_id: str = typer.Argument(..., help="Which crawler to run (see `list`)."),
    save_dir: Path = typer.Option(
        Path("data"),
        "--save-dir",
        help="Directory to write JSON snapshots into.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Render a results table."),
) -> None:
    """Run one crawler end-to-end and write its snapshot to disk."""
    try:
        cls = get_crawler(source_id)
    except KeyError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None

    err.print(f"crawling [cyan]{source_id}[/cyan] · {cls.root_url}")
    result: CrawlResult = cls().crawl()

    stamp = result.crawled_at.strftime("%Y-%m-%d")
    save_path = save_dir / source_id / f"{stamp}.json"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    err.print(
        f"wrote [green]{save_path}[/green] · "
        f"{result.record_count} records · {result.pages_fetched} pages"
    )
    if result.review_queue:
        err.print(f"[yellow]{len(result.review_queue)} items flagged for review[/yellow]")

    if verbose:
        _render_records_table(result.records)


@app.command("describe")
def describe_cmd(source_id: str = typer.Argument(...)) -> None:
    """Structured self-description of one crawler."""
    try:
        cls = get_crawler(source_id)
    except KeyError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    out.print_json(json.dumps(cls().describe(), indent=2))


def _render_records_table(records: list[Record]) -> None:
    if not records:
        return
    table = Table(show_edge=False)
    table.add_column("title", style="cyan", overflow="fold", max_width=60)
    table.add_column("type")
    table.add_column("entity")
    table.add_column("actions")
    table.add_column("date")
    for r in records:
        table.add_row(
            r.title,
            r.document_type,
            r.entity or "-",
            ", ".join(r.actions) or "-",
            str(r.published_at) if r.published_at else "-",
        )
    out.print(table)


if __name__ == "__main__":
    app()
