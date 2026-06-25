from crowdparser.output.json_file import JsonFileOutput
from crowdparser.output.webhook import WebhookOutput
from crowdparser.config import OutputConfig


def build_output(cfg: OutputConfig, field_map: dict = {}):
    if cfg.type == "json":
        return JsonFileOutput(cfg, field_map)
    if cfg.type == "webhook":
        return WebhookOutput(cfg, field_map)
    raise NotImplementedError(f"Output type '{cfg.type}' not implemented yet")
