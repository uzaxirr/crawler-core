"""crawler-core CLI.

Commands:
    crawler-core list                     show every registered crawler
    crawler-core run <source_id>          run one, snapshot to data/<id>/<date>.json
    crawler-core run --all                run every registered crawler
    crawler-core describe <source_id>     structured self-description
    crawler-core discover <url>           report which sub-listings under <url>
                                          are covered by registered crawlers
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import typer
from bs4 import BeautifulSoup
from rich.console import Console
from rich.table import Table

# Importing sources triggers @register on every module.
import crawler_core.sources  # noqa: F401
from crawler_core.base import all_sources, get_crawler
from crawler_core.http import http_get
from crawler_core.models import CrawlResult, Record


app = typer.Typer(no_args_is_help=True, add_completion=False)
out = Console()
err = Console(stderr=True)


@app.callback()
def _root() -> None:
    """Deterministic per-site crawlers with a plug-and-play registry."""


# ---- list -------------------------------------------------------------------


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


# ---- run --------------------------------------------------------------------


@app.command("run")
def run_cmd(
    source_id: Optional[str] = typer.Argument(
        None,
        help="Which crawler to run. Omit and pass --all to run everything.",
    ),
    all_: bool = typer.Option(
        False,
        "--all",
        help="Run every registered crawler in sequence.",
    ),
    save_dir: Path = typer.Option(
        Path("data"),
        "--save-dir",
        help="Directory to write JSON snapshots into.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Render a results table (single-crawler mode only).",
    ),
) -> None:
    """Run one crawler (or all of them) and write snapshots to disk."""
    if all_:
        if source_id is not None:
            err.print("[red]--all is mutually exclusive with a source_id argument[/red]")
            raise typer.Exit(1)
        _run_all(save_dir)
        return

    if not source_id:
        err.print("[red]specify a source_id or pass --all[/red]")
        raise typer.Exit(1)

    _run_one(source_id, save_dir, verbose)


def _run_one(source_id: str, save_dir: Path, verbose: bool) -> None:
    try:
        cls = get_crawler(source_id)
    except KeyError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None

    err.print(f"crawling [cyan]{source_id}[/cyan] · {cls.root_url}")
    result: CrawlResult = cls().crawl()

    save_path = _write_snapshot(result, save_dir)
    err.print(
        f"wrote [green]{save_path}[/green] · "
        f"{result.record_count} records · {result.pages_fetched} pages"
    )
    if result.review_queue:
        err.print(f"[yellow]{len(result.review_queue)} items flagged for review[/yellow]")

    if verbose:
        _render_records_table(result.records)


def _run_all(save_dir: Path) -> None:
    sources = all_sources()
    if not sources:
        err.print("[red]no crawlers registered[/red]")
        raise typer.Exit(1)

    err.print(f"[bold]running {len(sources)} crawler(s) sequentially[/bold]")

    rows: list[tuple[str, str, int, int, str]] = []
    for source_id in sources:
        cls = get_crawler(source_id)
        try:
            result = cls().crawl()
            save_path = _write_snapshot(result, save_dir)
            err.print(
                f"  [green]✓[/green] {source_id}: "
                f"{result.record_count} records, {result.pages_fetched} pages "
                f"→ {save_path}"
            )
            rows.append((source_id, "ok", result.record_count, result.pages_fetched, ""))
        except Exception as e:  # noqa: BLE001 — we want any failure to be surfaced, not raised
            err.print(f"  [red]✗[/red] {source_id}: {type(e).__name__}: {e}")
            rows.append((source_id, "error", 0, 0, f"{type(e).__name__}: {e}"))

    # Summary table
    table = Table(show_edge=False, title="run --all summary")
    table.add_column("source_id", style="cyan")
    table.add_column("status")
    table.add_column("records", justify="right")
    table.add_column("pages", justify="right")
    table.add_column("error")
    for source_id, status, count, pages, error in rows:
        badge = "[green]ok[/green]" if status == "ok" else "[red]error[/red]"
        table.add_row(source_id, badge, str(count), str(pages), error or "-")
    out.print(table)

    ok_count = sum(1 for r in rows if r[1] == "ok")
    total_records = sum(r[2] for r in rows if r[1] == "ok")
    err.print(
        f"[bold]{ok_count}/{len(rows)} crawlers succeeded · "
        f"{total_records} total records[/bold]"
    )

    if ok_count < len(rows):
        raise typer.Exit(1)


def _write_snapshot(result: CrawlResult, save_dir: Path) -> Path:
    stamp = result.crawled_at.strftime("%Y-%m-%d")
    save_path = save_dir / result.source_id / f"{stamp}.json"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return save_path


# ---- describe ---------------------------------------------------------------


@app.command("describe")
def describe_cmd(source_id: str = typer.Argument(...)) -> None:
    """Structured self-description of one crawler."""
    try:
        cls = get_crawler(source_id)
    except KeyError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    out.print_json(json.dumps(cls().describe(), indent=2))


# ---- discover ---------------------------------------------------------------


@app.command("discover")
def discover_cmd(
    url: str = typer.Argument(
        ...,
        help="Umbrella URL to introspect (e.g. https://www.fi.se/sv/publicerat/).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Discover sub-listings under <url> and report coverage.

    Fetches the page, extracts every same-host sub-path directly beneath it,
    then cross-checks each against every registered crawler's `root_url`.
    Answers: which listings on this site have crawlers, and which don't?
    """
    err.print(f"discovering sub-listings under [cyan]{url}[/cyan]")
    try:
        fetched = http_get(url)
    except Exception as e:  # noqa: BLE001 — surface any network/HTTP failure
        err.print(f"[red]fetch failed: {type(e).__name__}: {e}[/red]")
        raise typer.Exit(1) from None

    parent = urlparse(fetched.url)
    parent_path = parent.path if parent.path.endswith("/") else parent.path + "/"

    soup = BeautifulSoup(fetched.content, "lxml")
    subpaths: set[str] = set()

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        absolute = urljoin(fetched.url, href)
        parsed = urlparse(absolute)
        if parsed.netloc != parent.netloc:
            continue
        if not parsed.path.startswith(parent_path):
            continue
        if parsed.path == parent_path:
            continue
        rest = parsed.path[len(parent_path):]
        first_seg = rest.split("/", 1)[0]
        if not first_seg:
            continue
        subpaths.add(parent_path + first_seg + "/")

    # Cross-check against registered crawlers.
    registered = [(sid, get_crawler(sid).root_url) for sid in all_sources()]

    findings: list[dict[str, Any]] = []
    for subpath in sorted(subpaths):
        subpath_url = f"{parent.scheme}://{parent.netloc}{subpath}"
        matches = [sid for sid, root in registered if root.startswith(subpath_url)]
        findings.append(
            {
                "url": subpath_url,
                "covered": bool(matches),
                "source_ids": matches,
            }
        )

    if as_json:
        out.print_json(json.dumps(findings))
        return

    table = Table(show_edge=False)
    table.add_column("sub-listing URL", style="cyan", overflow="fold")
    table.add_column("coverage")
    table.add_column("source_id(s)")
    for f in findings:
        badge = (
            "[green]✓ covered[/green]"
            if f["covered"]
            else "[yellow]· uncovered[/yellow]"
        )
        sids = ", ".join(f["source_ids"]) or "-"
        table.add_row(f["url"], badge, sids)
    out.print(table)

    covered = sum(1 for f in findings if f["covered"])
    total = len(findings)
    err.print(f"[bold]{covered}/{total} discovered sub-listings covered[/bold]")


# ---- helpers ----------------------------------------------------------------


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
