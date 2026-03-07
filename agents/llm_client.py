"""
KoboldCpp LLM client for the agentic system.
Supports model switching between Qwen 3.5 4B (main) and Qwen 1.5B (support).
Only one model runs at a time.
"""
import httpx
import json
import time
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class LLMClient:
    """Client for KoboldCpp API. Manages model switching and prompt execution."""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.base_url = self.config.get("koboldcpp_url", "http://localhost:5001")
        self.main_model = self.config.get("main_model", {})
        self.support_model = self.config.get("support_model", {})
        self.current_model = "main"  # Track which model is active
        self.connected = False

    async def check_connection(self) -> bool:
        """Check if KoboldCpp is running and responsive."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/v1/model")
                self.connected = response.status_code == 200
                if self.connected:
                    data = response.json()
                    logger.info(f"KoboldCpp connected. Model: {data.get('result', 'unknown')}")
                return self.connected
        except Exception as e:
            logger.warning(f"KoboldCpp not available: {e}")
            self.connected = False
            return False

    async def generate(self, prompt: str, max_tokens: int = None,
                       temperature: float = None, use_support: bool = False) -> Optional[str]:
        """Generate text using KoboldCpp API.
        
        Args:
            prompt: The prompt to send to the model
            max_tokens: Override max tokens (uses model config default if None)
            temperature: Override temperature (uses model config default if None)
            use_support: If True, uses the support model (1.5B) instead of main (4B)
        """
        if not self.connected:
            await self.check_connection()
            if not self.connected:
                return None

        # Select model config
        model_cfg = self.support_model if use_support else self.main_model
        max_len = max_tokens or model_cfg.get("max_tokens", 1024)
        temp = temperature or model_cfg.get("temperature", 0.7)

        payload = {
            "prompt": prompt,
            "max_length": max_len,
            "temperature": temp,
            "top_p": 0.9,
            "top_k": 40,
            "rep_pen": 1.1,
            "stop_sequence": ["\n\n---", "###", "\nHuman:", "\nUser:"],
        }

        try:
            start_time = time.time()
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/generate",
                    json=payload
                )
                response.raise_for_status()
                result = response.json()

            elapsed = int((time.time() - start_time) * 1000)
            text = result.get("results", [{}])[0].get("text", "").strip()

            model_name = model_cfg.get("name", "unknown")
            logger.info(f"LLM [{model_name}] generated {len(text)} chars in {elapsed}ms")

            return text

        except httpx.TimeoutException:
            logger.warning("KoboldCpp request timed out")
            return None
        except Exception as e:
            logger.error(f"KoboldCpp generation error: {e}")
            return None

    async def decompose_task(self, task_description: str) -> list:
        """Use the support model (1.5B) to break a complex task into subtasks."""
        prompt = f"""<|im_start|>system
You are a task decomposition assistant. Break complex analysis tasks into clear, actionable subtasks.
Respond with a JSON array of subtask strings only, no explanations.
<|im_end|>
<|im_start|>user
Break this analysis task into 3-5 subtasks:
{task_description}
<|im_end|>
<|im_start|>assistant
["""

        result = await self.generate(prompt, max_tokens=512, temperature=0.3, use_support=True)
        if not result:
            return [task_description]

        try:
            # Try to parse as JSON array
            cleaned = "[" + result.split("]")[0] + "]"
            subtasks = json.loads(cleaned)
            if isinstance(subtasks, list):
                return subtasks
        except (json.JSONDecodeError, IndexError):
            pass

        # Fallback: split by newlines
        lines = [l.strip().lstrip("0123456789.-) ") for l in result.split("\n") if l.strip()]
        return lines if lines else [task_description]

    async def analyze_patterns(self, context: str) -> Optional[str]:
        """Use the main model (4B) to reason about patterns in data."""
        prompt = f"""<|im_start|>system
You are an intelligence analyst for a multi-domain data monitoring system called "Something from Everything."
Your job is to analyze patterns in collected data and generate actionable insights.
Be specific, cite data points, and suggest concrete next steps.
Keep your analysis concise but thorough.
<|im_end|>
<|im_start|>user
Analyze these patterns and generate insights:

{context}

Provide your analysis in the following format:
INSIGHT: [one-line summary]
CONFIDENCE: [0.0-1.0]
SEVERITY: [low/medium/high/critical]
ANALYSIS: [detailed reasoning]
ACTIONS: [recommended next steps]
<|im_end|>
<|im_start|>assistant
"""
        return await self.generate(prompt, max_tokens=2048, temperature=0.7, use_support=False)

    async def synthesize_insight(self, analytics_results: str,
                                  raw_data_summary: str) -> Optional[str]:
        """Use the main model to synthesize analytics into human-readable insights."""
        prompt = f"""<|im_start|>system
You are a senior analyst synthesizing automated analytics results with raw data into clear, 
actionable intelligence briefs. Focus on practical implications and cross-domain connections.
<|im_end|>
<|im_start|>user
Analytics Results:
{analytics_results}

Raw Data Summary:
{raw_data_summary}

Synthesize this into a clear intelligence brief with:
1. Key finding (one sentence)
2. Why this matters
3. Cross-domain connections
4. Recommended actions (2-3 specific steps)
<|im_end|>
<|im_start|>assistant
"""
        return await self.generate(prompt, max_tokens=1024, temperature=0.6, use_support=False)

    async def get_status(self) -> Dict[str, Any]:
        """Get current LLM status info."""
        status = {
            "connected": self.connected,
            "base_url": self.base_url,
            "current_model": self.current_model,
        }

        if self.connected:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(f"{self.base_url}/api/v1/model")
                    if resp.status_code == 200:
                        status["model_info"] = resp.json()
            except Exception:
                pass

        return status
