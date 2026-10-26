"""PSALM-SAGA v2: dimension-controlled synthesis of literary texts."""

from psalm_saga.artifacts import Bible, ChapterDraft, Plan, Spec, TransformMap
from psalm_saga.config import PipelineConfig, load_config, preset_names
from psalm_saga.pipeline import Pipeline
from psalm_saga.sdk import Run, Saga
from psalm_saga.stages.base import RunContext, Stage, register

__version__ = "2.0.0a1"

__all__ = [
    "Bible", "ChapterDraft", "Pipeline", "PipelineConfig", "Plan", "Run", "RunContext", "Saga", "Spec", "Stage",
    "TransformMap", "load_config", "preset_names", "register",
]
