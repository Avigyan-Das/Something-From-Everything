"""
Insight agent — uses Qwen 3.5 4B via KoboldCpp to synthesize
analytics results into enhanced, human-readable insights.
"""
import json
import logging
from typing import List
from datetime import datetime
from core.database import Database
from core.models import Insight, SeverityLevel
from agents.llm_client import LLMClient

logger = logging.getLogger(__name__)


class InsightAgent:
    """Enhances raw analytics insights using LLM reasoning."""

    def __init__(self, db: Database, llm: LLMClient):
        self.db = db
        self.llm = llm

    async def enhance_insights(self, analytics_insights: List[Insight],
                                 data_items: List[dict]) -> List[Insight]:
        """Take analytics insights and raw data, use LLM to generate deeper insights."""
        if not self.llm.connected:
            logger.info("LLM not connected, skipping enhancement")
            return []

        enhanced = []

        # Group related insights for batch analysis
        high_priority = [i for i in analytics_insights
                          if i.severity in ("critical", "high") and i.insight_type != "topic_cluster"]

        if not high_priority:
            # If no high-priority, take top 3 by confidence
            high_priority = sorted([i for i in analytics_insights if i.insight_type != "topic_cluster"],
                                    key=lambda x: x.confidence, reverse=True)[:3]

        if high_priority:
            # Build context for LLM
            analytics_summary = self._format_insights_for_llm(high_priority)
            data_summary = self._format_data_for_llm(data_items[:50])

            try:
                # Use support model to decompose the analysis task
                subtasks = await self.llm.decompose_task(
                    f"Analyze these {len(high_priority)} insights and {len(data_items)} data points "
                    f"to find hidden patterns, connections, and actionable opportunities."
                )
                logger.info(f"Task decomposed into {len(subtasks)} subtasks")

                # Use main model to synthesize insights
                llm_response = await self.llm.synthesize_insight(
                    analytics_summary, data_summary
                )

                if llm_response:
                    # Parse LLM response into insight
                    insight = self._parse_llm_insight(llm_response, high_priority)
                    if insight:
                        enhanced.append(insight)

            except Exception as e:
                logger.error(f"Insight enhancement failed: {e}")

        # Process significant clusters to generate narratives
        significant_clusters = [i for i in analytics_insights if i.insight_type == "topic_cluster" and i.metadata.get("is_significant")]
        
        for cluster_insight in significant_clusters[:5]:
            cluster_id = cluster_insight.metadata.get("cluster_id")
            cluster_data = [item for item in data_items if item.get("id") in cluster_insight.supporting_data]
            
            try:
                summary_prompt = (
                    f"Analyze this cluster of {len(cluster_data)} data items identified by keywords: "
                    f"{', '.join(cluster_insight.metadata.get('keywords', []))}. "
                    "What is the underlying narrative of this cluster? Why does it matter right now? "
                    "What is the predicted next step? Format your response clearly."
                )
                await self.llm.decompose_task(summary_prompt)
                
                data_summary = self._format_data_for_llm(cluster_data)
                llm_response = await self.llm.synthesize_insight(
                    f"Cluster Info: {cluster_insight.title} \n {cluster_insight.description}", data_summary
                )
                
                if llm_response:
                    narrative_insight = self._parse_llm_insight(llm_response, [cluster_insight])
                    if narrative_insight:
                        narrative_insight.title = f"Narrative: {cluster_insight.title.replace('Topic cluster: ', '')}"
                        narrative_insight.insight_type = "cluster_narrative"
                        # High severity if confidence is high since it's an evolving meaningful narrative
                        if narrative_insight.confidence > 0.8:
                            narrative_insight.severity = SeverityLevel.HIGH
                        enhanced.append(narrative_insight)
                        
                        if self.db and cluster_id:
                            await self.db.db.execute(
                                "UPDATE topic_clusters SET narrative_summary = ? WHERE id = ?", 
                                (llm_response[:2000], cluster_id)
                            )
                            await self.db.db.commit()
            except Exception as e:
                logger.error(f"Failed to synthesize narrative for cluster {cluster_insight.title}: {e}")

        return enhanced

    def _format_insights_for_llm(self, insights: List[Insight]) -> str:
        """Format analytics insights for LLM consumption."""
        lines = []
        for i, insight in enumerate(insights[:10]):
            lines.append(f"{i + 1}. [{insight.severity.upper()}] {insight.title}")
            lines.append(f"   Type: {insight.insight_type} | Confidence: {insight.confidence:.2f}")
            lines.append(f"   {insight.description[:200]}")
            if insight.domains:
                lines.append(f"   Domains: {', '.join(insight.domains)}")
            lines.append("")
        return "\n".join(lines)

    def _format_data_for_llm(self, data_items: List[dict]) -> str:
        """Format raw data for LLM consumption."""
        lines = []
        for item in data_items[:30]:
            source = item.get("source", "?")
            category = item.get("category", "?")
            title = item.get("title", "?")[:100]
            lines.append(f"- [{source}/{category}] {title}")
        return "\n".join(lines)

    def _parse_llm_insight(self, response: str, source_insights: List[Insight]) -> Insight:
        """Parse LLM response into a structured Insight object."""
        try:
            # Extract key fields from response
            title = "AI-Enhanced Analysis"
            confidence = 0.6
            severity = SeverityLevel.MEDIUM

            lines = response.strip().split("\n")
            for line in lines:
                line_lower = line.lower().strip()
                if line_lower.startswith("insight:"):
                    title = line.split(":", 1)[1].strip()
                elif line_lower.startswith("confidence:"):
                    try:
                        confidence = float(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                elif line_lower.startswith("severity:"):
                    sev_str = line.split(":", 1)[1].strip().lower()
                    sev_map = {
                        "critical": SeverityLevel.CRITICAL,
                        "high": SeverityLevel.HIGH,
                        "medium": SeverityLevel.MEDIUM,
                        "low": SeverityLevel.LOW,
                    }
                    severity = sev_map.get(sev_str, SeverityLevel.MEDIUM)

            return Insight(
                title=title,
                description=response[:2000],
                insight_type="llm_synthesis",
                confidence=min(max(confidence, 0.0), 1.0),
                severity=severity,
                supporting_data=[i.id for i in source_insights[:5]],
                domains=list(set(d for i in source_insights for d in i.domains)),
                metadata={
                    "model": "qwen3.5-4b",
                    "source_insights": len(source_insights),
                    "enhanced": True,
                },
                recommended_actions=["Review AI analysis for accuracy",
                                      "Verify connections against raw data"]
            )

        except Exception as e:
            logger.error(f"Failed to parse LLM insight: {e}")
            return None
