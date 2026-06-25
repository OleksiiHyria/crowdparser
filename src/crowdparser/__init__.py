"""crowdparser — harvest structured candidates from YouTube, Telegram, Reddit, and web."""
__version__ = "0.1.0"
__all__ = ["Pipeline", "run_pipeline", "PipelineConfig", "RawItem", "Candidate"]


def __getattr__(name):
    if name in ("Pipeline", "run_pipeline"):
        from crowdparser.pipeline import Pipeline, run_pipeline
        return {"Pipeline": Pipeline, "run_pipeline": run_pipeline}[name]
    if name == "PipelineConfig":
        from crowdparser.config import PipelineConfig
        return PipelineConfig
    if name == "RawItem":
        from crowdparser.models import RawItem
        return RawItem
    if name == "Candidate":
        from crowdparser.models import Candidate
        return Candidate
    raise AttributeError(f"module 'crowdparser' has no attribute {name!r}")
