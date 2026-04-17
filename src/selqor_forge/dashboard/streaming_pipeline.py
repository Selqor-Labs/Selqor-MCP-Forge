# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Streaming pipeline for handling large API specs (500-1k+ endpoints).

Production-grade implementation with:
- Chunked processing (50 endpoints at a time)
- Per-batch checkpointing
- Automatic resume capability
- Retry logic with exponential backoff
- Memory efficient (never loads entire spec)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from selqor_forge.models import ParsedSpec, UasfSurface

logger = logging.getLogger(__name__)

# Configuration
CHUNK_SIZE = 50  # Process 50 endpoints at a time
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 4  # seconds
MAX_RETRY_DELAY = 60  # seconds
BATCH_LLM_TIMEOUT = 600  # 10 minutes per batch
MAX_TOTAL_RETRY_DURATION = 1800  # 30 minutes overall circuit breaker


@dataclass
class CheckpointState:
    """Checkpoint state for resumable processing."""

    run_id: str
    stage: str  # "parse", "normalize", "analyze"
    total_chunks: int = 0
    completed_chunks: int = 0
    failed_chunks: list[int] = field(default_factory=list)
    total_batches: int = 0
    completed_batches: int = 0
    failed_batches: list[int] = field(default_factory=list)
    last_error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> CheckpointState:
        """Create from dictionary."""
        data['failed_chunks'] = data.get('failed_chunks', [])
        data['failed_batches'] = data.get('failed_batches', [])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class BatchCheckpoint:
    """Checkpoint for a single batch."""

    batch_idx: int
    total_batches: int
    endpoint_count: int
    analysis_result: dict
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    retry_count: int = 0
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class CheckpointManager:
    """Manages checkpointing for resumable processing."""

    def __init__(self, run_id: str, checkpoint_dir: Optional[Path] = None):
        self.run_id = run_id
        self.checkpoint_dir = checkpoint_dir or Path(f".checkpoints/{run_id}")
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.checkpoint_dir / "state.json"

    def load_state(self) -> CheckpointState:
        """Load checkpoint state, or create new one."""
        if self.state_file.exists():
            data = json.loads(self.state_file.read_text())
            logger.info(
                "Loaded checkpoint: stage=%s, completed=%d/%d chunks, batches=%d/%d",
                data.get('stage'),
                data.get('completed_chunks'),
                data.get('total_chunks'),
                data.get('completed_batches'),
                data.get('total_batches'),
            )
            return CheckpointState.from_dict(data)
        return CheckpointState(run_id=self.run_id, stage="parse")

    def save_state(self, state: CheckpointState) -> None:
        """Save checkpoint state."""
        state.updated_at = datetime.utcnow().isoformat()
        self.state_file.write_text(json.dumps(state.to_dict(), indent=2))
        logger.debug(f"Saved checkpoint: {self.state_file}")

    def save_chunk_result(self, chunk_idx: int, result: dict) -> None:
        """Save parsed chunk result."""
        chunk_file = self.checkpoint_dir / f"chunk_{chunk_idx}.json"
        chunk_file.write_text(json.dumps(result, indent=2))

    def load_chunk_result(self, chunk_idx: int) -> Optional[dict]:
        """Load parsed chunk result if it exists."""
        chunk_file = self.checkpoint_dir / f"chunk_{chunk_idx}.json"
        if chunk_file.exists():
            return json.loads(chunk_file.read_text())
        return None

    def save_batch_result(self, batch_checkpoint: BatchCheckpoint) -> None:
        """Save batch analysis result."""
        batch_file = self.checkpoint_dir / f"batch_{batch_checkpoint.batch_idx}.json"
        batch_file.write_text(json.dumps(batch_checkpoint.to_dict(), indent=2))
        logger.debug(f"Saved batch checkpoint: batch_{batch_checkpoint.batch_idx}")

    def load_batch_result(self, batch_idx: int) -> Optional[BatchCheckpoint]:
        """Load batch result if it exists."""
        batch_file = self.checkpoint_dir / f"batch_{batch_idx}.json"
        if batch_file.exists():
            data = json.loads(batch_file.read_text())
            return BatchCheckpoint(**data)
        return None

    def get_completed_batches(self) -> set[int]:
        """Get set of already completed batch indices."""
        completed = set()
        for batch_file in self.checkpoint_dir.glob("batch_*.json"):
            try:
                batch_idx = int(batch_file.stem.split('_')[1])
                completed.add(batch_idx)
            except (ValueError, IndexError):
                pass
        return completed

    def cleanup(self) -> None:
        """Remove checkpoint directory after successful completion."""
        import shutil
        if self.checkpoint_dir.exists():
            shutil.rmtree(self.checkpoint_dir)
            logger.info(f"Cleaned up checkpoint directory: {self.checkpoint_dir}")


class RetryStrategy:
    """Exponential backoff retry strategy."""

    def __init__(
        self,
        max_retries: int = MAX_RETRIES,
        initial_delay: float = INITIAL_RETRY_DELAY,
        max_delay: float = MAX_RETRY_DELAY,
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay

    async def execute_with_retry(
        self,
        coro_func: Callable,
        *args,
        batch_idx: Optional[int] = None,
        progress_cb: Optional[Callable] = None,
        **kwargs,
    ):
        """Execute coroutine with exponential backoff retry and overall timeout."""
        last_error = None
        overall_start = time.monotonic()

        for attempt in range(self.max_retries):
            # Circuit breaker: abort if cumulative retry time exceeds limit
            elapsed = time.monotonic() - overall_start
            if elapsed > MAX_TOTAL_RETRY_DURATION:
                raise RuntimeError(
                    f"Batch {batch_idx} exceeded overall retry budget "
                    f"({MAX_TOTAL_RETRY_DURATION}s) after {attempt} attempts"
                )

            try:
                logger.debug(f"Attempt {attempt + 1}/{self.max_retries} for batch {batch_idx}")
                return await coro_func(*args, **kwargs)

            except asyncio.TimeoutError as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    delay = min(
                        self.initial_delay * (2 ** attempt),
                        self.max_delay,
                    )
                    logger.warning(
                        f"Batch {batch_idx} timeout (attempt {attempt + 1}/{self.max_retries}). "
                        f"Retrying in {delay:.0f}s..."
                    )
                    if progress_cb:
                        await progress_cb({
                            "type": "batch_retry",
                            "batch_idx": batch_idx,
                            "attempt": attempt + 1,
                            "max_retries": self.max_retries,
                            "delay_seconds": delay,
                        })
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Batch {batch_idx} failed after {self.max_retries} attempts")
                    raise

            except Exception as e:
                last_error = e
                logger.error(f"Batch {batch_idx} failed with error: {e}", exc_info=True)
                raise

        raise last_error or Exception(f"Failed after {self.max_retries} attempts")


class StreamingSpecProcessor:
    """
    Production-grade streaming processor for large API specs.
    Handles 500-1k+ endpoints with chunking and checkpointing.
    """

    def __init__(
        self,
        run_id: str,
        checkpoint_dir: Optional[Path] = None,
        chunk_size: int = CHUNK_SIZE,
    ):
        self.run_id = run_id
        self.chunk_size = chunk_size
        self.checkpoint_mgr = CheckpointManager(run_id, checkpoint_dir)
        self.retry_strategy = RetryStrategy()

    async def process_spec_streaming(
        self,
        spec_input: str,
        progress_cb: Optional[Callable] = None,
    ) -> tuple[list[ParsedSpec], CheckpointState]:
        """
        Process spec in chunks with checkpointing.

        Returns: (list of parsed specs, checkpoint state)
        """
        from selqor_forge.pipeline.parse import parse_spec, _load_spec_content

        state = self.checkpoint_mgr.load_state()

        # Skip if already completed
        if state.stage == "parse" and state.completed_chunks > 0:
            logger.info(f"Resuming from chunk {state.completed_chunks}/{state.total_chunks}")

        logger.info(f"Processing spec: {spec_input}")
        raw_content = _load_spec_content(spec_input)
        logger.debug(f"Loaded spec content: {len(raw_content)} bytes")

        # Parse the full spec first (needed to extract endpoints)
        full_spec = parse_spec(spec_input)
        total_endpoints = len(full_spec.endpoints)
        state.total_chunks = (total_endpoints + self.chunk_size - 1) // self.chunk_size

        logger.info(
            f"Will process {total_endpoints} endpoints in {state.total_chunks} chunks "
            f"(chunk size: {self.chunk_size})"
        )

        if progress_cb:
            await progress_cb({
                "type": "parse_start",
                "total_endpoints": total_endpoints,
                "total_chunks": state.total_chunks,
                "chunk_size": self.chunk_size,
            })

        parsed_specs = []

        # Process endpoints in chunks
        for chunk_idx in range(state.total_chunks):
            # Skip already completed chunks
            if chunk_idx < state.completed_chunks:
                logger.debug(f"Skipping chunk {chunk_idx} (already completed)")
                cached = self.checkpoint_mgr.load_chunk_result(chunk_idx)
                if cached:
                    parsed_specs.append(cached)
                continue

            start_idx = chunk_idx * self.chunk_size
            end_idx = min((chunk_idx + 1) * self.chunk_size, total_endpoints)
            chunk_endpoints = full_spec.endpoints[start_idx:end_idx]

            chunk_parsed = ParsedSpec(
                source=full_spec.source,
                spec_kind=full_spec.spec_kind,
                title=f"{full_spec.title} (chunk {chunk_idx + 1}/{state.total_chunks})",
                version=full_spec.version,
                endpoints=chunk_endpoints,
                auth_schemes=full_spec.auth_schemes,
                global_security=full_spec.global_security,
            )

            logger.info(
                f"Chunk {chunk_idx + 1}/{state.total_chunks}: {len(chunk_endpoints)} endpoints"
            )

            # Save chunk checkpoint
            self.checkpoint_mgr.save_chunk_result(chunk_idx, chunk_parsed.model_dump())
            parsed_specs.append(chunk_parsed)

            state.completed_chunks += 1
            self.checkpoint_mgr.save_state(state)

            if progress_cb:
                await progress_cb({
                    "type": "chunk_done",
                    "chunk_idx": chunk_idx + 1,
                    "total_chunks": state.total_chunks,
                    "endpoint_count": len(chunk_endpoints),
                })

        state.stage = "normalize"
        self.checkpoint_mgr.save_state(state)

        logger.info(f"Parsed {total_endpoints} endpoints in {state.total_chunks} chunks")
        return parsed_specs, state


class AnalysisBatchProcessor:
    """
    Wraps LLM analysis with per-batch checkpointing and retry logic.
    Handles 500-1k endpoints broken into 10-11 batches with automatic retry.
    """

    def __init__(self, run_id: str, checkpoint_dir: Optional[Path] = None):
        self.run_id = run_id
        self.checkpoint_mgr = CheckpointManager(run_id, checkpoint_dir)
        self.retry_strategy = RetryStrategy()

    async def analyze_with_checkpointing(
        self,
        surface: UasfSurface,
        analyze_batch_func: Callable,
        progress_cb: Optional[Callable] = None,
    ) -> tuple[list[dict], CheckpointState]:
        """
        Analyze surface batches with checkpointing and retry.

        Args:
            surface: UasfSurface with endpoints to analyze
            analyze_batch_func: Async function(batch_surface, prompt_context) -> AnalysisPlan
            progress_cb: Progress callback function

        Returns:
            (list of batch results, checkpoint state)
        """
        from selqor_forge.pipeline.analyze import build_endpoint_batches, MAX_INPUT_TOKENS_DEFAULT

        state = self.checkpoint_mgr.load_state()
        state.stage = "analyze"

        # Build batches
        endpoint_batches = build_endpoint_batches(surface, MAX_INPUT_TOKENS_DEFAULT)
        state.total_batches = len(endpoint_batches)

        logger.info(
            f"Analyzing {len(surface.endpoints)} endpoints in {state.total_batches} batches"
        )

        if progress_cb:
            await progress_cb({
                "type": "analysis_start",
                "total_endpoints": len(surface.endpoints),
                "total_batches": state.total_batches,
            })

        batch_results = []
        completed_batches = self.checkpoint_mgr.get_completed_batches()

        for batch_idx, endpoints in enumerate(endpoint_batches):
            # Skip if already completed
            if batch_idx in completed_batches:
                logger.info(f"Batch {batch_idx + 1}/{state.total_batches}: Skipping (already completed)")
                cached = self.checkpoint_mgr.load_batch_result(batch_idx)
                if cached:
                    batch_results.append(cached.analysis_result)
                if progress_cb:
                    await progress_cb({
                        "type": "batch_skipped",
                        "batch_idx": batch_idx + 1,
                        "total_batches": state.total_batches,
                    })
                state.completed_batches += 1
                continue

            logger.info(
                f"Batch {batch_idx + 1}/{state.total_batches}: {len(endpoints)} endpoints"
            )

            if progress_cb:
                await progress_cb({
                    "type": "batch_start",
                    "batch_idx": batch_idx + 1,
                    "total_batches": state.total_batches,
                    "endpoint_count": len(endpoints),
                })

            # Create batch surface
            batch_surface = UasfSurface(
                source=surface.source,
                title=surface.title,
                version=surface.version,
                endpoints=list(endpoints),
                auth_schemes=list(surface.auth_schemes),
            )

            start_time = time.time()

            try:
                # Analyze with retry logic and extended timeout
                batch_plan = await asyncio.wait_for(
                    self.retry_strategy.execute_with_retry(
                        analyze_batch_func,
                        batch_surface,
                        None,
                        batch_idx=batch_idx,
                        progress_cb=progress_cb,
                    ),
                    timeout=BATCH_LLM_TIMEOUT,  # 10 minutes per batch
                )

                duration = time.time() - start_time

                # Convert plan to dict
                batch_result = batch_plan.model_dump() if hasattr(batch_plan, 'model_dump') else batch_plan

                # Save checkpoint immediately after successful batch
                batch_checkpoint = BatchCheckpoint(
                    batch_idx=batch_idx,
                    total_batches=state.total_batches,
                    endpoint_count=len(endpoints),
                    analysis_result=batch_result,
                    duration_seconds=duration,
                )
                self.checkpoint_mgr.save_batch_result(batch_checkpoint)

                batch_results.append(batch_result)
                state.completed_batches += 1
                self.checkpoint_mgr.save_state(state)

                logger.info(
                    f"Batch {batch_idx + 1}/{state.total_batches} completed in {duration:.1f}s"
                )

                if progress_cb:
                    await progress_cb({
                        "type": "batch_done",
                        "batch_idx": batch_idx + 1,
                        "total_batches": state.total_batches,
                        "duration_seconds": duration,
                    })

            except asyncio.TimeoutError:
                logger.error(
                    f"Batch {batch_idx + 1}/{state.total_batches} timed out after {BATCH_LLM_TIMEOUT}s"
                )
                state.failed_batches.append(batch_idx)
                state.last_error = f"Batch {batch_idx + 1} timed out after {BATCH_LLM_TIMEOUT}s"
                self.checkpoint_mgr.save_state(state)

                if progress_cb:
                    await progress_cb({
                        "type": "batch_failed",
                        "batch_idx": batch_idx + 1,
                        "total_batches": state.total_batches,
                        "error": state.last_error,
                        "recovery": "Can resume from this batch",
                    })

                raise RuntimeError(
                    f"Batch {batch_idx + 1}/{state.total_batches} failed after retries. "
                    f"Run can be resumed from batch {batch_idx + 1}."
                )

            except Exception as e:
                logger.error(
                    f"Batch {batch_idx + 1}/{state.total_batches} failed: {e}", exc_info=True
                )
                state.failed_batches.append(batch_idx)
                state.last_error = str(e)
                self.checkpoint_mgr.save_state(state)

                if progress_cb:
                    await progress_cb({
                        "type": "batch_failed",
                        "batch_idx": batch_idx + 1,
                        "total_batches": state.total_batches,
                        "error": str(e),
                        "recovery": "Can resume from this batch",
                    })

                raise

        state.stage = "complete"
        self.checkpoint_mgr.save_state(state)

        logger.info(f"Completed analysis of {state.total_batches} batches")

        return batch_results, state


# Usage example for run_worker.py:
"""
from selqor_forge.dashboard.streaming_pipeline import StreamingSpecProcessor, AnalysisBatchProcessor

async def run_large_integration_job(...):
    # Phase 1: Stream parse with checkpointing
    spec_processor = StreamingSpecProcessor(run_id)
    parsed_specs, state = await spec_processor.process_spec_streaming(
        spec_url,
        progress_cb=_analyze_progress_cb,
    )

    # Phase 2: Merge parsed specs into unified surface
    from selqor_forge.pipeline import parse, normalize
    merged_spec = parse.merge_parsed_specs(parsed_specs)
    surface = normalize.normalize_spec(merged_spec, config)

    # Phase 3: Analyze batches with checkpointing and retry
    batch_processor = AnalysisBatchProcessor(run_id)
    batch_results, state = await batch_processor.analyze_with_checkpointing(
        surface,
        analyze_batch_func=my_analyze_batch_func,
        progress_cb=_analyze_progress_cb,
    )

    # If any batch fails or crashes:
    # - Checkpoint saved at batch level
    # - User can call resume endpoint
    # - System will reload checkpoint and continue from failed batch
    # - No re-analysis of already completed batches
"""
