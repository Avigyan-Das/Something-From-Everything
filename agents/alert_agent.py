"""
Alert agent — monitors insight severity and generates alerts.
"""
import logging
from typing import List
from core.database import Database
from core.models import Insight, Alert, SeverityLevel

logger = logging.getLogger(__name__)


class AlertAgent:
    """Evaluates insights and generates alerts when thresholds are met."""

    def __init__(self, db: Database, config: dict = None):
        self.db = db
        self.config = config or {}
        self.severity_thresholds = config.get("severity_levels", {}) if config else {}

    async def evaluate_insights(self, insights: List[Insight]) -> List[Alert]:
        """Evaluate insights and generate alerts for significant ones."""
        alerts = []

        for insight in insights:
            alert = self._should_alert(insight)
            if alert:
                alerts.append(alert)

        logger.info(f"Generated {len(alerts)} alerts from {len(insights)} insights")
        return alerts

    def _should_alert(self, insight: Insight) -> Alert:
        """Determine if an insight warrants an alert."""
        # Alert on critical and high severity insights with sufficient confidence
        critical_threshold = self.severity_thresholds.get("critical", 0.9)
        high_threshold = self.severity_thresholds.get("high", 0.7)

        should_alert = False
        if insight.severity == SeverityLevel.CRITICAL and insight.confidence >= critical_threshold - 0.3:
            should_alert = True
        elif insight.severity == SeverityLevel.HIGH and insight.confidence >= high_threshold - 0.2:
            should_alert = True
        elif insight.confidence >= 0.85:  # Very high confidence always alerts
            should_alert = True

        if should_alert:
            return Alert(
                insight_id=insight.id,
                title=f"🔔 {insight.title}",
                message=insight.description[:500],
                severity=insight.severity
            )

        return None
