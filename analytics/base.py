"""
Abstract base class for all analytics modules.
"""
from abc import ABC, abstractmethod
from typing import List
from core.models import Insight
import logging


class BaseAnalyzer(ABC):
    """Base class for analytics modules. Implement analyze() for new analytics."""

    def __init__(self, name: str, config: dict = None):
        self.name = name
        self.config = config or {}
        self.logger = logging.getLogger(f"analytics.{name}")

    @abstractmethod
    async def analyze(self, data_items: List[dict]) -> List[Insight]:
        """Analyze data items and return discovered insights."""
        pass

    async def run(self, data_items: List[dict]) -> List[Insight]:
        try:
            self.logger.info(f"[{self.name}] Analyzing {len(data_items)} items...")
            insights = await self.analyze(data_items)
            self.logger.info(f"[{self.name}] Generated {len(insights)} insights")
            return insights
        except Exception as e:
            self.logger.error(f"[{self.name}] Analysis failed: {e}")
            return []
