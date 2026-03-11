"""
Global free-stream ingestion jobs (GDELT + phishing feed).
"""
import csv
import gc
import io
import logging
import zipfile
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from core.database import Database
from core.models import DataCategory, DataItem, DataSource


logger = logging.getLogger("sfe.global_streams")


def _safe_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _push_highest(store: List[Tuple[float, Dict]], value: float, item: Dict, top_n: int):
    store.append((value, item))
    store.sort(key=lambda x: x[0], reverse=True)
    if len(store) > top_n:
        store.pop()


def _push_lowest(store: List[Tuple[float, Dict]], value: float, item: Dict, top_n: int):
    store.append((value, item))
    store.sort(key=lambda x: x[0])
    if len(store) > top_n:
        store.pop()


def _parse_gdelt_lastupdate(text: str) -> Optional[str]:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 3 and parts[2].endswith(".export.CSV.zip"):
            return parts[2]
        if ".export.CSV.zip" in line and "http" in line:
            idx = line.find("http")
            return line[idx:].split()[0]
    return None


def _event_row_to_record(row: List[str], tone: Optional[float], goldstein: Optional[float]) -> Dict:
    source_url = row[57] if len(row) > 57 else None
    return {
        "global_event_id": row[0] if len(row) > 0 else None,
        "event_date": row[1] if len(row) > 1 else None,
        "actor1": row[6] if len(row) > 6 else None,
        "actor2": row[16] if len(row) > 16 else None,
        "event_code": row[26] if len(row) > 26 else None,
        "goldstein": goldstein,
        "tone": tone,
        "source_url": source_url,
    }


def _extract_tld(url: str) -> Optional[str]:
    candidate = url.strip()
    if not candidate:
        return None

    if "://" not in candidate:
        candidate = f"http://{candidate}"

    try:
        host = (urlparse(candidate).hostname or "").lower().strip(".")
    except Exception:
        return None

    if not host or "." not in host:
        return None

    return f".{host.split('.')[-1]}"


async def run_gdelt_extremes_job(
    db: Database,
    lastupdate_url: str = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt",
    top_n: int = 10,
):
    logger.info("GDELT job: start")

    zip_bytes = None
    tone_high: List[Tuple[float, Dict]] = []
    tone_low: List[Tuple[float, Dict]] = []
    gold_high: List[Tuple[float, Dict]] = []
    gold_low: List[Tuple[float, Dict]] = []

    try:
        timeout = httpx.Timeout(connect=10.0, read=45.0, write=20.0, pool=20.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            lastupdate_resp = await client.get(lastupdate_url)
            lastupdate_resp.raise_for_status()
            csv_zip_url = _parse_gdelt_lastupdate(lastupdate_resp.text)
            if not csv_zip_url:
                logger.warning("GDELT job: could not parse lastupdate.txt")
                return

            zip_resp = await client.get(csv_zip_url)
            zip_resp.raise_for_status()
            zip_bytes = zip_resp.content

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            csv_names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
            if not csv_names:
                logger.warning("GDELT job: zip contains no CSV")
                return

            with zf.open(csv_names[0]) as csv_file:
                text_wrapper = io.TextIOWrapper(csv_file, encoding="utf-8", errors="ignore", newline="")
                reader = csv.reader(text_wrapper, delimiter="\t")

                for row in reader:
                    if len(row) <= 34:
                        continue

                    goldstein = _safe_float(row[30])
                    tone = _safe_float(row[34])
                    if goldstein is None and tone is None:
                        continue

                    record = _event_row_to_record(row, tone=tone, goldstein=goldstein)

                    if tone is not None:
                        _push_highest(tone_high, tone, record, top_n)
                        _push_lowest(tone_low, tone, record, top_n)
                    if goldstein is not None:
                        _push_highest(gold_high, goldstein, record, top_n)
                        _push_lowest(gold_low, goldstein, record, top_n)

        captured_at = datetime.utcnow().isoformat()
        output_groups = [
            ("Tone High", tone_high),
            ("Tone Low", tone_low),
            ("Goldstein High", gold_high),
            ("Goldstein Low", gold_low),
        ]

        for label, values in output_groups:
            if not values:
                continue

            events = [item for _, item in values]
            item = DataItem(
                title=f"GDELT extremes ({label})",
                content=f"Top {len(events)} {label.lower()} events in latest 15-minute GDELT batch.",
                source=DataSource.WEB_SCRAPER,
                category=DataCategory.WORLD_NEWS,
                metadata={
                    "pipeline": "gdelt_extremes",
                    "metric_group": label,
                    "captured_at": captured_at,
                    "events": events,
                },
            )
            await db.store_data_item(item)

        logger.info("GDELT job: persisted extremes")

    except Exception as exc:
        logger.warning("GDELT job failed: %s", exc)
    finally:
        # Ensure raw payload objects are released quickly.
        del zip_bytes
        del tone_high
        del tone_low
        del gold_high
        del gold_low
        gc.collect()


async def run_phish_tld_job(
    db: Database,
    feed_url: str = "https://openphish.com/feed.txt",
    top_n: int = 5,
):
    logger.info("Phish feed job: start")

    tld_counts: Counter[str] = Counter()

    try:
        timeout = httpx.Timeout(connect=10.0, read=45.0, write=20.0, pool=20.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", feed_url) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    tld = _extract_tld(line)
                    if tld:
                        tld_counts[tld] += 1

        if not tld_counts:
            logger.info("Phish feed job: no TLD data in this run")
            return

        top_tlds = tld_counts.most_common(top_n)
        captured_at = datetime.utcnow().isoformat()
        item = DataItem(
            title="OpenPhish TLD abuse leaderboard",
            content=f"Top {len(top_tlds)} TLDs hosting malicious URLs in the latest hourly window.",
            source=DataSource.WEB_SCRAPER,
            category=DataCategory.TECHNOLOGY,
            metadata={
                "pipeline": "openphish_tld_aggregation",
                "feed_url": feed_url,
                "captured_at": captured_at,
                "top_tlds": [{"tld": tld, "count": count} for tld, count in top_tlds],
            },
        )
        await db.store_data_item(item)
        logger.info("Phish feed job: persisted top TLDs")

    except Exception as exc:
        logger.warning("Phish feed job failed: %s", exc)
    finally:
        tld_counts.clear()
        del tld_counts
        gc.collect()
