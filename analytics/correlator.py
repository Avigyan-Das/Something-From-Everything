"""
Cross-domain correlation finder.
The "secret sauce" — connects weather to markets, news to social trends, etc.
"""
from typing import List, Dict, Tuple
from collections import defaultdict
from datetime import datetime
from core.models import Insight, SeverityLevel
from analytics.base import BaseAnalyzer
import math


class CorrelationAnalyzer(BaseAnalyzer):
    def __init__(self, config: dict = None, db=None):
        super().__init__("correlator", config)
        self.min_correlation = config.get("min_correlation", 0.6) if config else 0.6
        self.min_data_points = config.get("min_data_points", 5) if config else 5
        self.db = db

    async def analyze(self, data_items: List[dict]) -> List[Insight]:
        if len(data_items) < self.min_data_points:
            return []

        insights = []

        # ── Analysis 1: Volume correlation between categories ──
        vol_insights = self._correlate_volumes(data_items)
        insights.extend(vol_insights)

        # ── Analysis 2: Sentiment-to-finance correlation ──
        fin_insights = self._correlate_sentiment_finance(data_items)
        insights.extend(fin_insights)

        # ── Analysis 3: Cross-cluster Domain Bleed ──
        cluster_insights = await self._correlate_clusters()
        insights.extend(cluster_insights)

        return insights

    def _correlate_volumes(self, data_items: List[dict]) -> List[Insight]:
        """Find categories whose data volumes rise and fall together."""
        insights = []

        # Group items by category and date
        daily_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for item in data_items:
            cat = item.get("category", "general")
            collected = item.get("collected_at", "")
            try:
                if isinstance(collected, str):
                    dt = datetime.fromisoformat(collected.replace("Z", "+00:00"))
                elif isinstance(collected, datetime):
                    dt = collected
                else:
                    continue
                day = dt.strftime("%Y-%m-%d")
            except (ValueError, AttributeError):
                continue
            daily_counts[cat][day] += 1

        categories = list(daily_counts.keys())
        if len(categories) < 2:
            return insights

        # Calculate correlation between each pair of categories
        for i in range(len(categories)):
            for j in range(i + 1, len(categories)):
                cat_a = categories[i]
                cat_b = categories[j]

                # Get shared dates
                shared_dates = sorted(set(daily_counts[cat_a].keys()) & set(daily_counts[cat_b].keys()))
                if len(shared_dates) < self.min_data_points:
                    continue

                series_a = [daily_counts[cat_a][d] for d in shared_dates]
                series_b = [daily_counts[cat_b][d] for d in shared_dates]

                correlation = self._pearson_correlation(series_a, series_b)
                if correlation is not None and abs(correlation) >= self.min_correlation:
                    direction = "positive" if correlation > 0 else "inverse"
                    insights.append(Insight(
                        title=f"{direction.title()} correlation: {cat_a} ↔ {cat_b}",
                        description=(f"Found {direction} correlation ({correlation:.2f}) between "
                                     f"'{cat_a}' and '{cat_b}' data volumes over {len(shared_dates)} days. "
                                     f"When one rises, the other {'rises' if correlation > 0 else 'falls'}."),
                        insight_type="volume_correlation",
                        confidence=abs(correlation),
                        severity=SeverityLevel.MEDIUM if abs(correlation) < 0.8 else SeverityLevel.HIGH,
                        domains=[cat_a, cat_b],
                        metadata={
                            "correlation": correlation,
                            "data_points": len(shared_dates),
                            "categories": [cat_a, cat_b]
                        },
                        recommended_actions=[
                            f"Monitor {cat_a} and {cat_b} together for connected events",
                            f"A spike in {cat_a} may predict movement in {cat_b}"
                        ]
                    ))

        return insights

    def _correlate_sentiment_finance(self, data_items: List[dict]) -> List[Insight]:
        """Correlate news sentiment with financial data changes."""
        insights = []

        # Separate finance and non-finance items
        finance_items = [i for i in data_items if i.get("category") == "finance"]
        news_items = [i for i in data_items if i.get("category") in ("world_news", "technology", "social")]

        if len(finance_items) < 3 or len(news_items) < 3:
            return insights

        # Get daily financial changes
        daily_changes: Dict[str, List[float]] = defaultdict(list)
        for item in finance_items:
            meta = item.get("metadata", {})
            if isinstance(meta, str):
                try:
                    import json
                    meta = json.loads(meta)
                except:
                    continue
            change = meta.get("change_pct", None)
            date = meta.get("date", "")
            if change is not None and date:
                daily_changes[date].append(change)

        if not daily_changes:
            return insights

        # Check if negative sentiment days correlate with negative market days
        avg_daily_change = {date: sum(changes) / len(changes)
                           for date, changes in daily_changes.items()}

        negative_market_days = [d for d, c in avg_daily_change.items() if c < -1.0]
        if negative_market_days:
            insights.append(Insight(
                title=f"Market decline detected: {len(negative_market_days)} day(s)",
                description=(f"Found {len(negative_market_days)} day(s) with average market decline > 1%. "
                             f"Days: {', '.join(negative_market_days[:5])}. "
                             f"Cross-referencing with news sentiment for correlation."),
                insight_type="market_sentiment_correlation",
                confidence=0.6,
                severity=SeverityLevel.HIGH,
                domains=["finance", "world_news"],
                metadata={"negative_days": negative_market_days[:5]},
                recommended_actions=[
                    "Check news sentiment on these dates",
                    "This pattern may indicate sentiment-driven market moves"
                ]
            ))

        return insights

    async def _correlate_clusters(self) -> List[Insight]:
        """Detect 'Domain Bleed': when a cluster is active in multiple unrelated domains."""
        insights = []
        if not self.db:
            return insights
            
        recent_clusters = await self.db.get_recent_topic_clusters(days=2, limit=20)
        
        for cluster in recent_clusters:
            active_domains = cluster.get("active_domains", [])
            size = cluster.get("size", 0)
            
            # Domain Bleed: Cluster spans multiple distinct categories
            if len(active_domains) > 1 and size >= self.min_data_points:
                insights.append(Insight(
                    title=f"Domain Bleed: {cluster.get('name')}",
                    description=(f"Topic '{cluster.get('name')}' is crossing boundaries and is active across "
                                 f"{len(active_domains)} distinct domains: {', '.join(active_domains)}. "
                                 f"This indicates a pervasive real-world event affecting multiple sectors."),
                    insight_type="domain_bleed",
                    confidence=min(0.5 + (len(active_domains) * 0.1), 0.95),
                    severity=SeverityLevel.HIGH if len(active_domains) >= 3 else SeverityLevel.MEDIUM,
                    domains=active_domains,
                    metadata={
                        "cluster_id": cluster.get("id"),
                        "size": size,
                        "base_category": cluster.get("base_category")
                    },
                    recommended_actions=[
                        f"Investigate root cause connecting these domains",
                        "Look for cascading effects"
                    ]
                ))
        return insights

    @staticmethod
    def _pearson_correlation(x: List[float], y: List[float]) -> float:
        """Calculate Pearson correlation coefficient."""
        n = len(x)
        if n < 3:
            return None

        mean_x = sum(x) / n
        mean_y = sum(y) / n

        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        denom_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
        denom_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))

        if denom_x == 0 or denom_y == 0:
            return None

        return numerator / (denom_x * denom_y)
