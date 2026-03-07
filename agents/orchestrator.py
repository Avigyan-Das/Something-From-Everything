"""
Agent orchestrator — coordinates data collection, analytics, and insight generation.
Uses the support model for task decomposition and main model for deep reasoning.
"""
import asyncio
import json
import logging
from typing import List, Optional
from datetime import datetime
from core.database import Database
from core.models import Insight, Alert, AgentAction, SeverityLevel
from agents.llm_client import LLMClient
from agents.insight_agent import InsightAgent
from agents.alert_agent import AlertAgent
from agents.memory import AgentMemory
from analytics.sentiment import SentimentAnalyzer
from analytics.trends import TrendAnalyzer
from analytics.correlator import CorrelationAnalyzer
from analytics.clustering import ClusteringAnalyzer

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Central coordinator for the agentic system."""

    def __init__(self, db: Database, llm: LLMClient, config: dict = None):
        self.db = db
        self.llm = llm
        self.config = config or {}

        # Initialize analytics modules
        analytics_cfg = self.config.get("analytics", {})
        self.analyzers = [
            SentimentAnalyzer(analytics_cfg.get("sentiment", {})),
            TrendAnalyzer(analytics_cfg.get("trends", {})),
            CorrelationAnalyzer(analytics_cfg.get("correlator", {}), db=self.db),
            ClusteringAnalyzer(analytics_cfg.get("clustering", {}), db=self.db),
        ]

        # Initialize agents
        self.insight_agent = InsightAgent(db, llm)
        self.alert_agent = AlertAgent(db, config.get("alerts", {}) if config else {})
        self.memory = AgentMemory(db)

        self.last_analysis: Optional[datetime] = None

    async def run_full_pipeline(self) -> dict:
        """Execute the full analytics + agent pipeline."""
        start_time = datetime.utcnow()
        results = {
            "data_analyzed": 0,
            "analytics_insights": 0,
            "llm_insights": 0,
            "alerts_generated": 0,
            "duration_ms": 0,
        }

        try:
            # Step 1: Get recent data
            data_items = await self.db.get_recent_data_items(hours=48, limit=500)
            results["data_analyzed"] = len(data_items)

            if not data_items:
                logger.info("No data to analyze")
                return results

            logger.info(f"Analyzing {len(data_items)} data items...")

            # Step 2: Run all analytics modules
            all_insights: List[Insight] = []
            for analyzer in self.analyzers:
                try:
                    insights = await analyzer.run(data_items)
                    all_insights.extend(insights)
                except Exception as e:
                    logger.error(f"Analyzer {analyzer.name} failed: {e}")

            results["analytics_insights"] = len(all_insights)
            logger.info(f"Analytics generated {len(all_insights)} insights")

            # Step 3: Store analytics insights
            for insight in all_insights:
                try:
                    await self.db.store_insight(insight)
                except Exception as e:
                    logger.error(f"Failed to store insight: {e}")

            # Step 4: LLM-enhanced insight generation (if connected)
            if self.llm.connected and all_insights:
                try:
                    llm_insights = await self.insight_agent.enhance_insights(
                        all_insights, data_items
                    )
                    results["llm_insights"] = len(llm_insights)

                    for insight in llm_insights:
                        await self.db.store_insight(insight)
                except Exception as e:
                    logger.error(f"LLM insight generation failed: {e}")

            # Step 5: Generate alerts for high-severity insights
            combined_insights = all_insights
            alerts = await self.alert_agent.evaluate_insights(combined_insights)
            results["alerts_generated"] = len(alerts)

            for alert in alerts:
                try:
                    await self.db.store_alert(alert)
                except Exception as e:
                    logger.error(f"Failed to store alert: {e}")

            # Step 6: Log the action
            elapsed = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            results["duration_ms"] = elapsed

            action = AgentAction(
                agent_name="orchestrator",
                action_type="full_pipeline",
                input_summary=f"Analyzed {len(data_items)} items",
                output_summary=f"Generated {len(all_insights)} analytics + {results['llm_insights']} LLM insights, {len(alerts)} alerts",
                model_used="pipeline",
                duration_ms=elapsed
            )
            await self.db.store_agent_action(action)

            # Step 7: Store to memory
            await self.memory.store(
                "orchestrator",
                f"pipeline_run_{start_time.isoformat()}",
                json.dumps(results)
            )

            self.last_analysis = datetime.utcnow()
            logger.info(f"Pipeline complete in {elapsed}ms: {results}")

        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            results["error"] = str(e)

        return results

    async def run_quick_analysis(self, data_items: List[dict]) -> List[Insight]:
        """Run a quick analysis on specific data items (no LLM)."""
        all_insights: List[Insight] = []
        for analyzer in self.analyzers:
            try:
                insights = await analyzer.run(data_items)
                all_insights.extend(insights)
            except Exception:
                pass
        return all_insights
