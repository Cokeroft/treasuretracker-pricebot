"""
A simple bounded job queue for price-check requests.

Why a queue at all: each price-check job opens several Playwright browser
tabs and walks multiple TCGPlayer pages. Running many of these concurrently
across different Discord users would (a) hammer TCGPlayer and get us
rate-limited/blocked, and (b) spike memory on a single Railway instance.
So jobs are processed one-at-a-time by a single background worker, and at
most MAX_QUEUE_SIZE jobs may be waiting at once. Anything beyond that is
rejected immediately with a friendly "try again shortly" message rather
than piling up unbounded.

MAX_QUEUE_SIZE is just an env var (see config.py) -- change it on Railway
and redeploy/restart to take effect. No code changes needed.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

import config

logger = logging.getLogger(__name__)


@dataclass
class Job:
    job_id: str
    coro_factory: Callable[[], Awaitable[None]]
    description: str


class QueueFullError(Exception):
    pass


class PriceCheckQueue:
    def __init__(self, max_size: int | None = None):
        self.max_size = max_size if max_size is not None else config.MAX_QUEUE_SIZE
        self._queue: asyncio.Queue[Job] = asyncio.Queue(maxsize=self.max_size)
        self._worker_task: asyncio.Task | None = None

    def start(self):
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._run_worker())
            logger.info("Price check queue worker started (max_size=%s)", self.max_size)

    def queue_size(self) -> int:
        return self._queue.qsize()

    def is_full(self) -> bool:
        return self._queue.full()

    async def enqueue(self, job: Job) -> None:
        """
        Raises QueueFullError immediately if the queue is at capacity,
        rather than blocking the caller (so the bot can reply right away
        instead of hanging).
        """
        if self._queue.full():
            raise QueueFullError(
                f"Queue is full ({self.max_size} jobs already waiting)"
            )
        await self._queue.put(job)
        logger.info("Enqueued job %s (queue size now %s)", job.job_id, self._queue.qsize())

    async def _run_worker(self):
        while True:
            job = await self._queue.get()
            logger.info("Starting job %s: %s", job.job_id, job.description)
            try:
                await job.coro_factory()
            except Exception:
                logger.exception("Job %s failed", job.job_id)
            finally:
                self._queue.task_done()
