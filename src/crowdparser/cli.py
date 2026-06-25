import asyncio
import click
from rich.console import Console

console = Console()


@click.group()
def main():
    """crowdparser — harvest structured candidates from web sources."""
    pass


@main.command()
@click.argument("config", type=click.Path(exists=True))
def run(config: str):
    """Run the pipeline defined in CONFIG (YAML file)."""
    from crowdparser.pipeline import run_pipeline
    candidates = asyncio.run(run_pipeline(config))
    console.print(f"\n[bold green]Done.[/] {len(candidates)} candidates written.")


@main.command()
@click.argument("url")
@click.option("--source", type=click.Choice(["youtube", "telegram", "reddit", "web"]), default="web")
def fetch(url: str, source: str):
    """Quick fetch: dump raw content from a single URL."""
    from crowdparser.config import (
        YouTubeSourceConfig, WebSourceConfig,
        TelegramSourceConfig, RedditSourceConfig,
    )
    from crowdparser.sources import build_source

    cfg_map = {
        "youtube":  YouTubeSourceConfig(video_ids=[url.split("v=")[-1].split("&")[0]]),
        "web":      WebSourceConfig(urls=[url]),
    }
    if source not in cfg_map:
        console.print(f"[red]Quick fetch for '{source}' not supported — use a config file.[/]")
        return

    items = asyncio.run(build_source(cfg_map[source]).fetch())
    for item in items:
        console.print(f"\n[cyan]--- {item.source_url} ---[/]")
        console.print(item.content[:2000])


@main.command()
@click.argument("video_id")
def transcript(video_id: str):
    """Dump raw YouTube transcript for a video ID."""
    from crowdparser.sources.youtube import _get_transcript
    text = _get_transcript(video_id, ["pl", "uk", "ru", "en"])
    if text:
        console.print(text)
    else:
        console.print("[red]No transcript available.[/]")


if __name__ == "__main__":
    main()
