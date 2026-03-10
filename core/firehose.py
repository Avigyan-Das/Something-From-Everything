"""
Wikipedia recent-change firehose processor.
"""
import asyncio
import json
import logging
import time
from collections import Counter, deque
from datetime import datetime
from typing import Deque, Optional, Tuple
from urllib.parse import quote

import websockets

from core.database import Database
from core.models import DataCategory, DataItem, DataSource


logger = logging.getLogger("sfe.firehose")


class WikipediaFirehose:
    def __init__(
        self,
        db: Database,
        stream_url: str = "wss://stream.wikimedia.org/v2/stream/recentchange",
        window_seconds: int = 300,
        flush_interval_seconds: int = 300,
        top_n: int = 3,
        reconnect_delay_seconds: int = 5,
    ):
        self.db = db
        self.stream_url = stream_url
        self.window_seconds = max(60, window_seconds)
        self.flush_interval_seconds = max(60, flush_interval_seconds)
        self.top_n = max(1, top_n)
        self.reconnect_delay_seconds = max(1, reconnect_delay_seconds)

        self._events: Deque[Tuple[float, str]] = deque()
        self._counts: Counter[str] = Counter()

        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._flush_task: Optional[asyncio.Task] = None

    def start(self):
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self.run(), name="wikipedia-firehose")

    async def stop(self):
        self._stop_event.set()

        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            await asyncio.gather(self._flush_task, return_exceptions=True)

        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def run(self):
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(
                    self.stream_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    max_queue=1000,
                ) as ws:
                    logger.info("Wikipedia firehose connected")
                    self._flush_task = asyncio.create_task(
                        self._flush_loop(), name="wikipedia-firehose-flush"
                    )

                    while not self._stop_event.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=3)
                        except asyncio.TimeoutError:
                            continue

                        await self.process_message(raw)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Wikipedia firehose reconnecting after error: %s", exc)
                await asyncio.sleep(self.reconnect_delay_seconds)
            finally:
                if self._flush_task and not self._flush_task.done():
                    self._flush_task.cancel()
                    await asyncio.gather(self._flush_task, return_exceptions=True)
                self._flush_task = None

        logger.info("Wikipedia firehose stopped")

    async def process_message(self, raw: str):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return

        if event.get("type") != "edit":
            return

        title = (event.get("title") or "").strip()
        if not title:
            return

        now = time.monotonic()
        self._events.append((now, title))
        self._counts[title] += 1
        self._evict_old(now)

    def _evict_old(self, now_monotonic: float):
        cutoff = now_monotonic - self.window_seconds
        while self._events and self._events[0][0] < cutoff:
            _, title = self._events.popleft()
            self._counts[title] -= 1
            if self._counts[title] <= 0:
                del self._counts[title]

    async def _flush_loop(self):
        while not self._stop_event.is_set():
            await asyncio.sleep(self.flush_interval_seconds)
            await self.flush_top_topics()

    async def flush_top_topics(self):
        now = time.monotonic()
        self._evict_old(now)

        if not self._counts:
            self._events.clear()
            return

        top_topics = self._counts.most_common(self.top_n)
        captured_at = datetime.utcnow().isoformat()

        for rank, (title, edit_count) in enumerate(top_topics, start=1):
            wiki_slug = quote(title.replace(" ", "_"))
            item = DataItem(
                title=f"Wikipedia trend #{rank}: {title}",
                content=(
                    f"{title} had {edit_count} edits in the last "
                    f"{int(self.window_seconds / 60)} minutes."
                ),
                url=f"https://en.wikipedia.org/wiki/{wiki_slug}",
                source=DataSource.WEB_SCRAPER,
                category=DataCategory.WORLD_NEWS,
                metadata={
                    "pipeline": "wikipedia_recentchange_firehose",
                    "window_seconds": self.window_seconds,
                    "rank": rank,
                    "edit_count": edit_count,
                    "captured_at": captured_at,
                },
            )
            await self.db.store_data_item(item)

        logger.info(
            "Wikipedia firehose persisted top %s topics for %s-second window",
            min(self.top_n, len(top_topics)),
            self.window_seconds,
        )

        # Reset counters after each write cycle per requirement.
        self._counts.clear()
        self._events.clear()
