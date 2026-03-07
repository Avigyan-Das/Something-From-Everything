"""
Abstract base class for all data collectors.
"""
from abc import ABC, abstractmethod
from typing import List
from core.models import DataItem
from core.database import Database
import logging

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Base class for all data collectors. Implement collect() to add a new source."""

    def __init__(self, name: str, db: Database, config: dict = None):
        self.name = name
        self.db = db
        self.config = config or {}
        self.logger = logging.getLogger(f"collector.{name}")

    @abstractmethod
    async def collect(self) -> List[DataItem]:
        """Fetch data from the source and return normalized DataItems."""
        pass

    async def run(self) -> int:
        """Execute collection pipeline: collect → store. Returns count stored."""
        try:
            self.logger.info(f"[{self.name}] Starting collection...")
            items = await self.collect()
            if items:
                count = await self.db.store_data_items(items)
                self.logger.info(f"[{self.name}] Stored {count}/{len(items)} items")
                return count
            else:
                self.logger.info(f"[{self.name}] No items collected")
                return 0
        except Exception as e:
            self.logger.error(f"[{self.name}] Collection failed: {e}")
            return 0
