"""
Financial data collector using Yahoo Finance public endpoints.
"""
import httpx
from typing import List
from datetime import datetime
from core.models import DataItem, DataSource, DataCategory
from core.database import Database
from collectors.base import BaseCollector
import hashlib
import json


class FinanceCollector(BaseCollector):
    def __init__(self, db: Database, config: dict = None):
        super().__init__("finance", db, config)
        self.symbols = config.get("symbols", []) if config else []

    async def collect(self) -> List[DataItem]:
        items = []
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True,
                                      headers={"User-Agent": "SFE-Bot/1.0"}) as client:
            for symbol in self.symbols:
                try:
                    symbol_items = await self._collect_symbol(client, symbol)
                    items.extend(symbol_items)
                except Exception as e:
                    self.logger.warning(f"Failed to collect {symbol}: {e}")
        return items

    async def _collect_symbol(self, client: httpx.AsyncClient, symbol: str) -> List[DataItem]:
        """Fetch quote data for a symbol from Yahoo Finance."""
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {
            "range": "5d",
            "interval": "1d",
            "includePrePost": "false",
        }

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            self.logger.warning(f"Yahoo Finance API error for {symbol}: {e}")
            return []

        chart = data.get("chart", {}).get("result", [])
        if not chart:
            return []

        result = chart[0]
        meta = result.get("meta", {})
        timestamps = result.get("timestamp", [])
        indicators = result.get("indicators", {}).get("quote", [{}])[0]

        closes = indicators.get("close", [])
        opens = indicators.get("open", [])
        highs = indicators.get("high", [])
        lows = indicators.get("low", [])
        volumes = indicators.get("volume", [])

        items = []
        name = meta.get("shortName", meta.get("symbol", symbol))
        currency = meta.get("currency", "USD")
        exchange = meta.get("exchangeName", "")

        for i, ts in enumerate(timestamps):
            if i >= len(closes) or closes[i] is None:
                continue

            dt = datetime.utcfromtimestamp(ts)
            date_str = dt.strftime("%Y-%m-%d")
            item_id = hashlib.md5(f"finance:{symbol}:{date_str}".encode()).hexdigest()

            close_price = round(closes[i], 2) if closes[i] else 0
            open_price = round(opens[i], 2) if i < len(opens) and opens[i] else 0
            high_price = round(highs[i], 2) if i < len(highs) and highs[i] else 0
            low_price = round(lows[i], 2) if i < len(lows) and lows[i] else 0
            volume = volumes[i] if i < len(volumes) and volumes[i] else 0

            # Calculate daily change
            prev_close = closes[i - 1] if i > 0 and closes[i - 1] else close_price
            change_pct = round(((close_price - prev_close) / prev_close) * 100, 2) if prev_close else 0

            title = f"{name} ({symbol}): ${close_price} ({'+' if change_pct >= 0 else ''}{change_pct}%)"
            content = (f"{name} closed at ${close_price} {currency} on {date_str}. "
                       f"Open: ${open_price}, High: ${high_price}, Low: ${low_price}. "
                       f"Volume: {volume:,}. Change: {change_pct}%.")

            items.append(DataItem(
                id=item_id,
                title=title,
                content=content,
                url=f"https://finance.yahoo.com/quote/{symbol}",
                source=DataSource.FINANCE_API,
                category=DataCategory.FINANCE,
                metadata={
                    "symbol": symbol,
                    "name": name,
                    "close": close_price,
                    "open": open_price,
                    "high": high_price,
                    "low": low_price,
                    "volume": volume,
                    "change_pct": change_pct,
                    "currency": currency,
                    "exchange": exchange,
                    "date": date_str,
                },
                collected_at=dt
            ))

        return items
