"""
Web scraper using httpx + BeautifulSoup + Scrapeling for smart scraping.
"""
import httpx
from bs4 import BeautifulSoup
from typing import List
from datetime import datetime
from core.models import DataItem, DataSource, DataCategory
from core.database import Database
from collectors.base import BaseCollector
import hashlib

# Try to import scrapeling for enhanced scraping
try:
    from scrapeling import Scraper as ScrapelingScraper
    HAS_SCRAPELING = True
except ImportError:
    HAS_SCRAPELING = False


class WebScraperCollector(BaseCollector):
    def __init__(self, db: Database, config: dict = None):
        super().__init__("web_scraper", db, config)
        self.targets = config.get("targets", []) if config else []

    async def collect(self) -> List[DataItem]:
        items = []
        for target in self.targets:
            try:
                target_items = await self._scrape_target(target)
                items.extend(target_items)
            except Exception as e:
                self.logger.warning(f"Failed to scrape {target.get('name', '?')}: {e}")
        return items

    async def _scrape_target(self, target: dict) -> List[DataItem]:
        url = target["url"]
        name = target.get("name", url)
        selector = target.get("selector", "article")
        title_selector = target.get("title_selector", "h2, h3, .title")
        content_selector = target.get("content_selector", "p")
        category = target.get("category", "general")

        # Use Scrapeling if available for JS-rendered pages
        if HAS_SCRAPELING and target.get("use_scrapeling", False):
            return await self._scrape_with_scrapeling(url, name, category, target)

        # Default: httpx + BeautifulSoup
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True,
                                      headers={"User-Agent": "SFE-Bot/1.0"}) as client:
            response = await client.get(url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        articles = soup.select(selector)[:30]
        items = []

        for article in articles:
            title_el = article.select_one(title_selector)
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue

            content_els = article.select(content_selector)
            content = " ".join(el.get_text(strip=True) for el in content_els)
            if not content:
                content = article.get_text(strip=True)[:2000]

            link_el = article.select_one("a[href]")
            link = link_el["href"] if link_el else url

            item_id = hashlib.md5(f"{link}:{title}".encode()).hexdigest()

            cat_map = {
                "world_news": DataCategory.WORLD_NEWS,
                "technology": DataCategory.TECHNOLOGY,
                "science": DataCategory.SCIENCE,
                "finance": DataCategory.FINANCE,
            }

            items.append(DataItem(
                id=item_id,
                title=title[:500],
                content=content[:5000],
                url=link,
                source=DataSource.WEB_SCRAPER,
                category=cat_map.get(category, DataCategory.GENERAL),
                metadata={"scraper_name": name, "source_url": url},
                collected_at=datetime.utcnow()
            ))

        return items

    async def _scrape_with_scrapeling(self, url: str, name: str, category: str,
                                       target: dict) -> List[DataItem]:
        """Use Scrapeling for smarter content extraction."""
        if not HAS_SCRAPELING:
            return []

        try:
            scraper = ScrapelingScraper()
            result = scraper.scrape(url)

            if not result or not result.text:
                return []

            # Scrapeling extracts clean text content
            title = result.title if hasattr(result, 'title') and result.title else name
            content = result.text[:5000]

            item_id = hashlib.md5(f"{url}:{title}".encode()).hexdigest()

            cat_map = {
                "world_news": DataCategory.WORLD_NEWS,
                "technology": DataCategory.TECHNOLOGY,
                "science": DataCategory.SCIENCE,
                "finance": DataCategory.FINANCE,
            }

            return [DataItem(
                id=item_id,
                title=title[:500],
                content=content,
                url=url,
                source=DataSource.WEB_SCRAPER,
                category=cat_map.get(category, DataCategory.GENERAL),
                metadata={
                    "scraper_name": name,
                    "source_url": url,
                    "scraper_engine": "scrapeling"
                },
                collected_at=datetime.utcnow()
            )]
        except Exception as e:
            self.logger.warning(f"Scrapeling failed for {url}: {e}")
            return []
