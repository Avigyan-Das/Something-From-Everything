"""
Trend detection module — time-series anomaly detection using
z-score analysis and rolling averages.
"""
from typing import List, Dict
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from core.models import Insight, SeverityLevel
from analytics.base import BaseAnalyzer
import math


class TrendAnalyzer(BaseAnalyzer):
    def __init__(self, config: dict = None):
        super().__init__("trends", config)
        self.z_threshold = config.get("z_score_threshold", 2.0) if config else 2.0
        self.rolling_window = config.get("rolling_window", 24) if config else 24

    async def analyze(self, data_items: List[dict]) -> List[Insight]:
        if not data_items:
            return []

        insights = []

        # ── Analysis 1: Volume anomaly detection ──
        volume_insights = self._detect_volume_anomalies(data_items)
        insights.extend(volume_insights)

        # ── Analysis 2: Keyword/topic velocity ──
        velocity_insights = self._detect_keyword_velocity(data_items)
        insights.extend(velocity_insights)

        # ── Analysis 3: Cross-domain trend emergence ──
        cross_insights = self._detect_cross_domain_trends(data_items)
        insights.extend(cross_insights)

        return insights

    def _detect_volume_anomalies(self, data_items: List[dict]) -> List[Insight]:
        """Detect unusual spikes in data volume by source/category."""
        insights = []

        # Group by category and hour
        hourly_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for item in data_items:
            cat = item.get("category", "general")
            collected = item.get("collected_at", "")
            if isinstance(collected, str) and collected:
                try:
                    dt = datetime.fromisoformat(collected.replace("Z", "+00:00"))
                except ValueError:
                    continue
            elif isinstance(collected, datetime):
                dt = collected
            else:
                continue
            hour_key = dt.strftime("%Y-%m-%d %H:00")
            hourly_counts[cat][hour_key] += 1

        for cat, hours in hourly_counts.items():
            if len(hours) < 3:
                continue

            values = list(hours.values())
            mean = sum(values) / len(values)
            if mean == 0:
                continue
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            std = math.sqrt(variance) if variance > 0 else 1

            for hour, count in hours.items():
                z_score = (count - mean) / std if std > 0 else 0
                if z_score > self.z_threshold:
                    insights.append(Insight(
                        title=f"Volume spike in {cat} at {hour}",
                        description=(f"Data volume in '{cat}' spiked to {count} items at {hour} "
                                     f"(mean: {mean:.1f}, z-score: {z_score:.1f}). "
                                     f"This is {z_score:.1f} standard deviations above normal."),
                        insight_type="volume_spike",
                        confidence=min(z_score / 5, 1.0),
                        severity=SeverityLevel.MEDIUM if z_score < 3 else SeverityLevel.HIGH,
                        domains=[cat],
                        recommended_actions=[
                            f"Investigate what caused the spike in {cat}",
                            "Check if this correlates with events in other domains"
                        ]
                    ))

        return insights

    def _detect_keyword_velocity(self, data_items: List[dict]) -> List[Insight]:
        """Detect rapidly rising keywords/topics."""
        insights = []

        # Split data into recent vs older
        now = datetime.utcnow()
        recent_cutoff = now - timedelta(hours=6)

        recent_words: Counter = Counter()
        older_words: Counter = Counter()

        for item in data_items:
            title = item.get("title", "").lower()
            words = [w for w in title.split() if len(w) > 4]  # Skip short words

            collected = item.get("collected_at", "")
            try:
                if isinstance(collected, str):
                    dt = datetime.fromisoformat(collected.replace("Z", "+00:00"))
                elif isinstance(collected, datetime):
                    dt = collected
                else:
                    dt = now
            except ValueError:
                dt = now

            if dt >= recent_cutoff:
                recent_words.update(words)
            else:
                older_words.update(words)

        # Find words that spiked in frequency
        if not recent_words or not older_words:
            return insights

        total_recent = sum(recent_words.values()) or 1
        total_older = sum(older_words.values()) or 1

        for word, count in recent_words.most_common(50):
            recent_freq = count / total_recent
            older_freq = older_words.get(word, 0) / total_older
            velocity = recent_freq / (older_freq + 0.001)

            if velocity > 3 and count >= 3:
                insights.append(Insight(
                    title=f"Trending keyword: '{word}'",
                    description=(f"The keyword '{word}' appeared {count} times in the last 6 hours "
                                 f"({velocity:.1f}x normal frequency). This may indicate an emerging topic."),
                    insight_type="keyword_velocity",
                    confidence=min(velocity / 10, 1.0),
                    severity=SeverityLevel.LOW,
                    metadata={"keyword": word, "velocity": velocity, "count": count},
                    recommended_actions=[
                        f"Monitor '{word}' for continued growth",
                        "Check related data sources for context"
                    ]
                ))

        return insights[:5]  # Limit to top 5 trending keywords

    def _detect_cross_domain_trends(self, data_items: List[dict]) -> List[Insight]:
        """Detect when multiple domains are talking about the same thing."""
        insights = []

        # Extract keywords per category
        category_keywords: Dict[str, Counter] = defaultdict(Counter)
        for item in data_items:
            cat = item.get("category", "general")
            title = item.get("title", "").lower()
            words = [w for w in title.split() if len(w) > 4]
            category_keywords[cat].update(words)

        if len(category_keywords) < 2:
            return insights

        # Find keywords appearing in multiple categories
        all_categories = list(category_keywords.keys())
        cross_keywords: Dict[str, List[str]] = defaultdict(list)

        for word in set().union(*[set(kw.keys()) for kw in category_keywords.values()]):
            cats_with_word = [cat for cat in all_categories
                              if category_keywords[cat].get(word, 0) >= 2]
            if len(cats_with_word) >= 2:
                cross_keywords[word] = cats_with_word

        # Report significant cross-domain keywords
        for word, cats in sorted(cross_keywords.items(),
                                  key=lambda x: len(x[1]), reverse=True)[:3]:
            total_mentions = sum(category_keywords[cat][word] for cat in cats)
            insights.append(Insight(
                title=f"Cross-domain trend: '{word}'",
                description=(f"The topic '{word}' is trending across {len(cats)} domains: "
                             f"{', '.join(cats)}. Total mentions: {total_mentions}."),
                insight_type="cross_domain_trend",
                confidence=min(len(cats) / 4, 1.0),
                severity=SeverityLevel.MEDIUM,
                domains=cats,
                metadata={"keyword": word, "total_mentions": total_mentions},
                recommended_actions=[
                    f"Investigate '{word}' across all domains",
                    "This cross-domain activity may indicate a significant event"
                ]
            ))

        return insights
