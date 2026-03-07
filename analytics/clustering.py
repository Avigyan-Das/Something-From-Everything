"""
Topic clustering module using TF-IDF + K-Means.
Groups related data items into topics automatically.
"""
from typing import List, Dict
from collections import Counter
from core.models import Insight, SeverityLevel
from analytics.base import BaseAnalyzer

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.cluster import KMeans
    import numpy as np
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


class ClusteringAnalyzer(BaseAnalyzer):
    def __init__(self, config: dict = None):
        super().__init__("clustering", config)
        self.max_clusters = config.get("max_clusters", 10) if config else 10
        self.min_cluster_size = config.get("min_cluster_size", 3) if config else 3

    async def analyze(self, data_items: List[dict]) -> List[Insight]:
        if not HAS_SKLEARN:
            self.logger.warning("scikit-learn not installed, skipping clustering")
            return []

        if len(data_items) < self.min_cluster_size * 2:
            return []

        insights = []

        # Prepare text corpus
        texts = []
        valid_items = []
        for item in data_items:
            text = f"{item.get('title', '')} {item.get('content', '')}"
            if text.strip() and len(text) > 20:
                texts.append(text[:1000])  # Limit per-item text
                valid_items.append(item)

        if len(texts) < self.min_cluster_size * 2:
            return insights

        try:
            # TF-IDF vectorization
            vectorizer = TfidfVectorizer(
                max_features=5000,
                stop_words='english',
                max_df=0.8,
                min_df=2,
                ngram_range=(1, 2)
            )
            tfidf_matrix = vectorizer.fit_transform(texts)
            feature_names = vectorizer.get_feature_names_out()

            # Determine optimal number of clusters (capped)
            n_clusters = min(self.max_clusters, len(texts) // self.min_cluster_size)
            n_clusters = max(2, n_clusters)

            # K-Means clustering
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10, max_iter=100)
            labels = kmeans.fit_predict(tfidf_matrix)

            # Analyze each cluster
            cluster_items: Dict[int, List[dict]] = {}
            for i, label in enumerate(labels):
                if label not in cluster_items:
                    cluster_items[label] = []
                cluster_items[label].append(valid_items[i])

            for label, items in cluster_items.items():
                if len(items) < self.min_cluster_size:
                    continue

                # Get top keywords for this cluster
                cluster_center = kmeans.cluster_centers_[label]
                top_keyword_indices = cluster_center.argsort()[-5:][::-1]
                top_keywords = [feature_names[i] for i in top_keyword_indices]

                # Get category distribution
                categories = Counter(i.get("category", "general") for i in items)
                sources = Counter(i.get("source", "unknown") for i in items)

                # Determine topic name from top keywords
                topic_name = " / ".join(top_keywords[:3])

                insights.append(Insight(
                    title=f"Topic cluster: {topic_name}",
                    description=(f"Found a cluster of {len(items)} related items about '{topic_name}'. "
                                 f"Keywords: {', '.join(top_keywords)}. "
                                 f"Categories: {dict(categories)}. Sources: {dict(sources)}."),
                    insight_type="topic_cluster",
                    confidence=min(len(items) / 20, 1.0),
                    severity=SeverityLevel.LOW,
                    supporting_data=[i.get("id", "") for i in items[:10]],
                    domains=list(categories.keys()),
                    metadata={
                        "cluster_id": int(label),
                        "keywords": top_keywords,
                        "size": len(items),
                        "categories": dict(categories),
                        "sources": dict(sources),
                    },
                    recommended_actions=[
                        f"Explore the '{topic_name}' cluster for deeper insights",
                        f"Cross-reference with other clusters for connections"
                    ]
                ))

        except Exception as e:
            self.logger.error(f"Clustering failed: {e}")

        return insights
