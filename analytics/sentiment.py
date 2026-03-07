"""
Sentiment analysis module using TextBlob.
Detects sentiment shifts and spikes across data.
"""
from typing import List, Dict
from collections import defaultdict
from datetime import datetime
from core.models import Insight, SeverityLevel
from analytics.base import BaseAnalyzer

try:
    from textblob import TextBlob
    HAS_TEXTBLOB = True
except ImportError:
    HAS_TEXTBLOB = False


class SentimentAnalyzer(BaseAnalyzer):
    def __init__(self, config: dict = None):
        super().__init__("sentiment", config)
        self.spike_threshold = config.get("spike_threshold", 0.3) if config else 0.3

    async def analyze(self, data_items: List[dict]) -> List[Insight]:
        if not HAS_TEXTBLOB:
            self.logger.warning("TextBlob not installed, skipping sentiment analysis")
            return []

        if not data_items:
            return []

        insights = []

        # Score all items
        scored_items = []
        for item in data_items:
            text = f"{item.get('title', '')} {item.get('content', '')}"
            if not text.strip():
                continue
            try:
                blob = TextBlob(text[:1000])  # Limit text length for performance
                score = blob.sentiment.polarity  # -1 to 1
                scored_items.append({**item, "_sentiment": score})
            except Exception:
                continue

        if not scored_items:
            return []

        # ── Analysis 1: Overall sentiment by category ──
        category_sentiments: Dict[str, List[float]] = defaultdict(list)
        for item in scored_items:
            cat = item.get("category", "general")
            category_sentiments[cat].append(item["_sentiment"])

        for cat, scores in category_sentiments.items():
            avg = sum(scores) / len(scores)
            if abs(avg) > self.spike_threshold:
                direction = "positive" if avg > 0 else "negative"
                severity = SeverityLevel.HIGH if abs(avg) > 0.5 else SeverityLevel.MEDIUM

                insights.append(Insight(
                    title=f"Strong {direction} sentiment in {cat}",
                    description=(f"Average sentiment in '{cat}' is {avg:.2f} across {len(scores)} items. "
                                 f"This indicates a {direction} trend in this domain."),
                    insight_type="sentiment_spike",
                    confidence=min(abs(avg), 1.0),
                    severity=severity,
                    supporting_data=[i.get("id", "") for i in scored_items if i.get("category") == cat][:10],
                    domains=[cat],
                    recommended_actions=[
                        f"Monitor {cat} data for continued {direction} sentiment",
                        f"Cross-reference with other domains for correlation"
                    ]
                ))

        # ── Analysis 2: Find extremely negative items (potential alerts) ──
        very_negative = [i for i in scored_items if i["_sentiment"] < -0.5]
        if len(very_negative) >= 3:
            insights.append(Insight(
                title=f"Cluster of highly negative content detected",
                description=(f"Found {len(very_negative)} items with sentiment below -0.5. "
                             f"Topics: {', '.join(set(i.get('category', '?') for i in very_negative[:5]))}."),
                insight_type="sentiment_cluster",
                confidence=0.7,
                severity=SeverityLevel.HIGH,
                supporting_data=[i.get("id", "") for i in very_negative[:10]],
                domains=list(set(i.get("category", "general") for i in very_negative)),
                recommended_actions=[
                    "Investigate the cause of negative sentiment",
                    "Check for correlation with market or social trends"
                ]
            ))

        # ── Analysis 3: Source-level sentiment comparison ──
        source_sentiments: Dict[str, List[float]] = defaultdict(list)
        for item in scored_items:
            src = item.get("source", "unknown")
            source_sentiments[src].append(item["_sentiment"])

        # Check for divergent sentiments between sources
        source_avgs = {src: sum(scores) / len(scores) for src, scores in source_sentiments.items() if scores}
        if len(source_avgs) >= 2:
            sorted_sources = sorted(source_avgs.items(), key=lambda x: x[1])
            lowest_src, lowest_avg = sorted_sources[0]
            highest_src, highest_avg = sorted_sources[-1]
            divergence = highest_avg - lowest_avg

            if divergence > 0.4:
                insights.append(Insight(
                    title=f"Sentiment divergence: {lowest_src} vs {highest_src}",
                    description=(f"Significant sentiment gap between sources. "
                                 f"{lowest_src}: {lowest_avg:.2f} vs {highest_src}: {highest_avg:.2f} "
                                 f"(divergence: {divergence:.2f})."),
                    insight_type="sentiment_divergence",
                    confidence=min(divergence, 1.0),
                    severity=SeverityLevel.MEDIUM,
                    domains=list(source_avgs.keys()),
                    recommended_actions=[
                        "Investigate why sources have divergent sentiments",
                        "May indicate emerging story not yet reflected everywhere"
                    ]
                ))

        return insights
