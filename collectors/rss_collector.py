"""
RSS/Atom feed collector using feedparser.
"""
import feedparser
import httpx
from typing import List
from datetime import datetime
from core.models import DataItem, DataSource, DataCategory
from core.database import Database
from collectors.base import BaseCollector
import hashlib


class RSSCollector(BaseCollector):
    def __init__(self, db: Database, config: dict = None):
        super().__init__("rss", db, config)
        self.feeds = config.get("feeds", []) if config else []

    async def collect(self) -> List[DataItem]:
        items = []
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for feed_cfg in self.feeds:
                try:
                    feed_items = await self._collect_feed(client, feed_cfg)
                    items.extend(feed_items)
                except Exception as e:
                    self.logger.warning(f"Failed to collect feed {feed_cfg.get('name', '?')}: {e}")
        return items

    async def _collect_feed(self, client: httpx.AsyncClient, feed_cfg: dict) -> List[DataItem]:
        url = feed_cfg["url"]
        name = feed_cfg.get("name", url)
        category = feed_cfg.get("category", "general")

        try:
            response = await client.get(url)
            response.raise_for_status()
        except Exception as e:
            self.logger.warning(f"HTTP error fetching {name}: {e}")
            return []

        feed = feedparser.parse(response.text)
        items = []

        for entry in feed.entries[:50]:  # Cap per feed
            title = entry.get("title", "No Title")
            # Build content from summary/description
            content = entry.get("summary", entry.get("description", ""))
            if not content:
                content = title
            link = entry.get("link", "")

            # Generate deterministic ID from URL to avoid duplicates
            item_id = hashlib.md5(f"{link}:{title}".encode()).hexdigest()

            # Parse published date
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published = datetime(*entry.published_parsed[:6])
                except Exception:
                    published = datetime.utcnow()
            else:
                published = datetime.utcnow()

            # Map category string to enum
            cat_map = {
                "world_news": DataCategory.WORLD_NEWS,
                "technology": DataCategory.TECHNOLOGY,
                "science": DataCategory.SCIENCE,
                "finance": DataCategory.FINANCE,
            }
            cat = cat_map.get(category, DataCategory.GENERAL)

            items.append(DataItem(
                id=item_id,
                title=title,
                content=content[:5000],  # Truncate long content
                url=link,
                source=DataSource.RSS,
                category=cat,
                metadata={
                    "feed_name": name,
                    "feed_url": url,
                    "author": entry.get("author", ""),
                },
                collected_at=published
            ))

        return items
