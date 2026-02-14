from __future__ import annotations

"""Memory Performance Evaluation Framework.

This package provides the core framework for evaluating AnimaWorks' memory system
performance according to the research protocol defined in:
docs/research/memory-performance-evaluation-protocol.md
"""

from .config import (
    ConversationLength,
    ConversationMetrics,
    Domain,
    ExperimentConfig,
    MemorySize,
    ScenarioType,
    SearchConfig,
    SearchMethod,
    TurnMetrics,
)
from .framework import MemoryExperiment, Scenario, Turn
from .logger import ExperimentLogger
from .metrics import MetricsCollector

__all__ = [
    # Config
    "ConversationLength",
    "ConversationMetrics",
    "Domain",
    "ExperimentConfig",
    "MemorySize",
    "ScenarioType",
    "SearchConfig",
    "SearchMethod",
    "TurnMetrics",
    # Framework
    "MemoryExperiment",
    "Scenario",
    "Turn",
    # Tools
    "ExperimentLogger",
    "MetricsCollector",
]
