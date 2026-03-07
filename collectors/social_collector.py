"""
Social media trend collector — Reddit (public JSON API) + HackerNews (public API).
No API keys required.
"""
import httpx
from typing import List
from datetime import datetime
from core.models import DataItem, DataSource, DataCategory
from core.database import Database
from collectors.base import BaseCollector
import hashlib


class SocialCollector(BaseCollector):
    def __init__(self, db: Database, config: dict = None):
        super().__init__("social", db, config)
        self.reddit_config = config.get("reddit", {}) if config else {}
        self.hn_config = config.get("hackernews", {}) if config else {}

    async def collect(self) -> List[DataItem]:
        items = []

        # Collect from Reddit
        reddit_items = await self._collect_reddit()
        items.extend(reddit_items)

        # Collect from HackerNews
        hn_items = await self._collect_hackernews()
        items.extend(hn_items)

        return items

    async def _collect_reddit(self) -> List[DataItem]:
        subreddits = self.reddit_config.get("subreddits", ["worldnews", "technology"])
        posts_per = self.reddit_config.get("posts_per_subreddit", 25)
        items = []

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True,
                                      headers={"User-Agent": "SFE-Bot/1.0 (data research)"}) as client:
            for subreddit in subreddits:
                try:
                    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={posts_per}"
                    response = await client.get(url)
                    response.raise_for_status()
                    data = response.json()

                    for post in data.get("data", {}).get("children", []):
                        post_data = post.get("data", {})
                        title = post_data.get("title", "")
                        if not title:
                            continue

                        selftext = post_data.get("selftext", "")[:3000]
                        content = selftext if selftext else title
                        permalink = post_data.get("permalink", "")
                        link = f"https://reddit.com{permalink}" if permalink else ""
                        score = post_data.get("score", 0)
                        num_comments = post_data.get("num_comments", 0)
                        created_utc = post_data.get("created_utc", 0)

                        item_id = hashlib.md5(f"reddit:{permalink}".encode()).hexdigest()

                        items.append(DataItem(
                            id=item_id,
                            title=title[:500],
                            content=content,
                            url=link,
                            source=DataSource.REDDIT,
                            category=DataCategory.SOCIAL,
                            metadata={
                                "subreddit": subreddit,
                                "score": score,
                                "num_comments": num_comments,
                                "upvote_ratio": post_data.get("upvote_ratio", 0),
                            },
                            collected_at=datetime.utcfromtimestamp(created_utc) if created_utc else datetime.utcnow()
                        ))

                except Exception as e:
                    self.logger.warning(f"Reddit r/{subreddit} failed: {e}")

        return items

    async def _collect_hackernews(self) -> List[DataItem]:
        top_count = self.hn_config.get("top_stories_count", 30)
        items = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                # Fetch top story IDs
                response = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json")
                response.raise_for_status()
                story_ids = response.json()[:top_count]

                # Fetch each story
                for story_id in story_ids:
                    try:
                        resp = await client.get(
                            f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
                        )
                        resp.raise_for_status()
                        story = resp.json()

                        if not story or story.get("type") != "story":
                            continue

                        title = story.get("title", "")
                        if not title:
                            continue

                        url = story.get("url", f"https://news.ycombinator.com/item?id={story_id}")
                        text = story.get("text", "")
                        content = text if text else title
                        score = story.get("score", 0)
                        descendants = story.get("descendants", 0)
                        created_time = story.get("time", 0)

                        item_id = hashlib.md5(f"hn:{story_id}".encode()).hexdigest()

                        items.append(DataItem(
                            id=item_id,
                            title=title[:500],
                            content=content[:5000],
                            url=url,
                            source=DataSource.HACKERNEWS,
                            category=DataCategory.TECHNOLOGY,
                            metadata={
                                "hn_id": story_id,
                                "score": score,
                                "comments": descendants,
                                "by": story.get("by", ""),
                            },
                            collected_at=datetime.utcfromtimestamp(created_time) if created_time else datetime.utcnow()
                        ))

                    except Exception as e:
                        self.logger.debug(f"HN story {story_id} failed: {e}")

            except Exception as e:
                self.logger.warning(f"HackerNews collection failed: {e}")

        return items
