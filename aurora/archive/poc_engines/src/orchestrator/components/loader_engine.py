#!/usr/bin/env python3
"""
Aurora Emulator - Phase 5: Loader Engine Component
====================================================

Wraps Phase 3's Markov prefetcher. On install, trains the model from a play
trace (if available). At runtime, sets AURORA_PREFETCH_MODEL and ENABLED=1.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

_SRC_ROOT = Path(__file__).resolve().parents[2]
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from loader_engine.predictive_prefetcher import (
    MarkovPrefetcher, generate_synthetic_play_trace, DEFAULT_PREFETCH_THRESHOLD,
)
from .base import EnvironmentComponent


class LoaderEngineComponent(EnvironmentComponent):
    """Phase 3 component: Markov-based predictive file prefetching."""

    def __init__(self, play_trace_path: Optional[Path] = None,
                 threshold: float = DEFAULT_PREFETCH_THRESHOLD):
        super().__init__(name="LoaderEngine")
        self.play_trace_path = play_trace_path
        self.threshold = threshold
        self.model_size_bytes: int = 0
        self.train_time_ms: float = 0.0

    def preprocess_on_install(self) -> None:
        """Train the Markov model on install. In production, the play trace
        would come from a community-uploaded trace for this game."""
        if not self.environment:
            raise RuntimeError("Component not attached to environment")
        out_dir = self.environment.image_fs.aurora_prefetch_path()
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"  [LoaderEngine] Training Markov prefetch model")
        print(f"  [LoaderEngine] Threshold: {self.threshold}")

        # For PoC, generate a synthetic play trace if none provided
        # In production: download community play trace from cloud
        trace, file_sizes = generate_synthetic_play_trace(
            num_levels=5, files_per_level=20, accesses_per_level=100, seed=42
        )

        t0 = time.perf_counter()
        model = MarkovPrefetcher(prefetch_threshold=self.threshold)
        model.train(trace, file_sizes)
        self.train_time_ms = (time.perf_counter() - t0) * 1000.0

        model_path = out_dir / "model.json"
        model.save(model_path)
        self.model_size_bytes = model_path.stat().st_size

        stats = model.stats()
        print(f"  [LoaderEngine] Trained in {self.train_time_ms:.1f}ms")
        print(f"  [LoaderEngine] States: {stats['states']}, Transitions: {stats['transitions']}")
        print(f"  [LoaderEngine] Model size: {self.model_size_bytes} bytes")

    def start(self) -> None:
        super().start()
        model_path = self.environment.image_fs.aurora_prefetch_path() / "model.json"
        if model_path.exists():
            print(f"  [LoaderEngine] Started. Model at {model_path}")
        else:
            print(f"  [LoaderEngine] Started. No model (run preprocess_on_install first)")
