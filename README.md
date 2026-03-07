# 🔮 Something from Everything

**Multi-utility intelligence platform that collects open web data, finds cross-domain patterns, and surfaces actionable insights.**

![Dashboard](https://img.shields.io/badge/Dashboard-Dark%20Mode-0a0a0f?style=for-the-badge&labelColor=111118)
![Python](https://img.shields.io/badge/Python-3.11+-00d4ff?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-a855f7?style=for-the-badge&logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-10b981?style=for-the-badge)

---

## What It Does

Something from Everything is a system that:
1. **Collects data** from the open web — news, social media, financial markets, weather, and more
2. **Analyzes patterns** using sentiment analysis, trend detection, cross-domain correlation, and topic clustering
3. **Generates insights** through an agentic system powered by local LLMs (KoboldCpp + Qwen)
4. **Surfaces opportunities** via a stunning real-time dashboard with alerts

> *Think of it as your personal intelligence analyst that watches everything on the web and tells you when something interesting is happening.*

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Data Collection Layer                  │
│  RSS Feeds │ Web Scraper │ Reddit │ HackerNews │ Finance │ Weather │
├─────────────────────────────────────────────────────────┤
│                     Core Engine                          │
│           Data Normalizer → SQLite Database              │
│                  APScheduler (Cron)                      │
├─────────────────────────────────────────────────────────┤
│                   Analytics Layer                        │
│  Sentiment │ Trend Detection │ Correlator │ Clustering   │
├─────────────────────────────────────────────────────────┤
│                   Agentic Layer                          │
│  KoboldCpp/Qwen 4B │ Task Decomposer 1.5B │ Memory     │
├─────────────────────────────────────────────────────────┤
│                   Presentation                           │
│          FastAPI + WebSocket + Glassmorphism UI          │
└─────────────────────────────────────────────────────────┘
```

---

## Quick Start

```bash
# Clone the repo
git clone https://github.com/Avigyan-Das/Something-From-Everything.git
cd Something-From-Everything

# Install dependencies
pip install -r requirements.txt

# Run the platform
python main.py

# Open dashboard
# → http://localhost:8000
```

---

## Data Sources (All Free, No API Keys)

| Source | What It Collects |
|---|---|
| **RSS/Atom Feeds** | Reuters, BBC, TechCrunch, NASA |
| **Reddit** | Trending posts from r/worldnews, r/technology, r/science, r/economics |
| **HackerNews** | Top stories from the tech community |
| **Yahoo Finance** | S&P 500, NASDAQ, Gold, Oil, Bitcoin, Ethereum |
| **Open-Meteo** | Weather for New York, London, Tokyo |
| **Web Scraper** | Configurable CSS-selector scraping + Scrapeling |

---

## Analytics Modules

- **Sentiment Analysis** — TextBlob-based scoring, tracks shifts and spikes by category
- **Trend Detection** — Z-score anomaly detection, keyword velocity, cross-domain emergence
- **Cross-Domain Correlator** — Pearson correlation between data streams (the "secret sauce")
- **Topic Clustering** — TF-IDF + K-Means auto-groups related items into topics

---

## Agentic System (Optional LLM)

The platform can run with or without a local LLM:

- **Without LLM**: Full analytics pipeline works using statistical methods
- **With LLM**: Start [KoboldCpp](https://github.com/LostRuins/koboldcpp) on `localhost:5001` with Qwen 3.5 4B for AI-enhanced insights

The system uses a dual-model approach:
- **Qwen 1.5B** (support) — Decomposes complex analysis into subtasks
- **Qwen 3.5 4B** (main) — Deep reasoning over patterns and data

Only one model runs at a time to conserve resources.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/data` | Paginated collected data |
| GET | `/api/insights` | Generated pattern insights |
| GET | `/api/alerts` | Active alerts |
| GET | `/api/stats` | System statistics |
| GET | `/api/sources` | Configured data sources |
| POST | `/api/collect/now` | Trigger immediate collection |
| POST | `/api/analyze/now` | Trigger immediate analysis |
| WS | `/ws/live` | Real-time dashboard updates |

---

## Configuration

Edit `config.yaml` to customize:
- Data sources and collection intervals
- Analytics thresholds
- KoboldCpp connection settings
- Alert severity levels

---

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, APScheduler
- **Database**: SQLite (async via aiosqlite)
- **Scraping**: httpx, BeautifulSoup4, feedparser, Scrapeling
- **Analytics**: TextBlob, scikit-learn, pandas
- **LLM**: KoboldCpp + Qwen 3.5 4B / 1.5B
- **Frontend**: Vanilla HTML/CSS/JS, WebSocket, Glassmorphism design

---

## License

MIT
