"""crowdparser — harvest structured candidates from YouTube, Telegram, Reddit, and web."""
from crowdparser.pipeline import Pipeline, run_pipeline
from crowdparser.config import PipelineConfig
from crowdparser.models import RawItem, Candidate

__all__ = ["Pipeline", "run_pipeline", "PipelineConfig", "RawItem", "Candidate"]
__version__ = "0.1.0"
