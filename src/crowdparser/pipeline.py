"""Main pipeline: sources → extract → dedup → output."""
from __future__ import annotations
import asyncio
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from crowdparser.config import PipelineConfig
from crowdparser.sources import build_source
from crowdparser.extractors.llm import LLMExtractor
from crowdparser.output import build_output
from crowdparser.dedup import Deduplicator
from crowdparser.models import Candidate

console = Console()


class Pipeline:
    def __init__(self, cfg: PipelineConfig):
        self._cfg = cfg
        self._extractor = LLMExtractor(cfg.extractor)
        self._output = build_output(cfg.output, cfg.field_map)
        self._dedup = Deduplicator(cfg.dedup)

    async def run(self) -> list[Candidate]:
        cfg = self._cfg
        console.print(f"[bold cyan]crowdparser[/] — {cfg.name}")

        all_items = []
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
            for source_cfg in cfg.sources:
                task = progress.add_task(f"Fetching {source_cfg.type}...", total=None)
                source = build_source(source_cfg)
                items = await source.fetch()
                all_items.extend(items)
                progress.update(task, description=f"[green]✓[/] {source_cfg.type} — {len(items)} items")

        console.print(f"[cyan]Fetched {len(all_items)} raw items[/]")

        all_candidates: list[Candidate] = []
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
            task = progress.add_task(f"Extracting candidates...", total=len(all_items))
            for item in all_items:
                candidates = self._extractor.extract(item)
                for c in candidates:
                    if self._dedup.is_new(c):
                        all_candidates.append(c)
                progress.advance(task)

        console.print(f"[green]✓ {len(all_candidates)} new candidates extracted[/]")

        if all_candidates:
            self._output.write(all_candidates)
            self._dedup.save()
            console.print(f"[green]✓ Written to {cfg.output.type}[/]")
        else:
            console.print("[yellow]No new candidates — nothing written[/]")

        return all_candidates


async def run_pipeline(config_path: str) -> list[Candidate]:
    cfg = PipelineConfig.from_yaml(config_path)
    pipeline = Pipeline(cfg)
    return await pipeline.run()
