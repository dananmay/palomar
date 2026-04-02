# Palomar — Cowork Project Prompt

## Project Overview

Palomar is an open-source, real-time OSINT (Open Source Intelligence) platform with an AI intelligence analyst layer. It is a fork of Shadowbroker (https://github.com/BigBodyCobain/Shadowbroker or https://gitlab.com/bigbodycobain/Shadowbroker) — an existing open-source OSINT dashboard that aggregates 60+ live public data feeds (aircraft tracking, maritime vessels, satellites, earthquakes, conflict zones, GPS jamming, CCTV networks, etc.) into a single map interface.

Shadowbroker is a "dumb" dashboard — it displays data but does not analyze it. Palomar adds the missing brain: an AI layer that watches all incoming feeds, detects anomalies, connects patterns across domains, and exposes a conversational interface where users can ask questions and receive intelligence briefings.

**One-line pitch:** "I took the viral OSINT dashboard and gave it a brain."

**Named after:** Mr. Palomar by Italo Calvino — a man whose chief activity is observing the world with extreme precision and finding patterns in what he sees.

**Epigraph for the README:**
> "It is only after you have come to know the surface of things that you can venture to seek what is underneath." — Italo Calvino, *Mr. Palomar*

## Goals

The primary goal is to create a GitHub repository that goes viral and accumulates a large number of stars. The project should be:

- Visually striking (the "intelligence command center" aesthetic that made Shadowbroker go viral)
- Easy to set up (Docker Compose, up and running in under 5 minutes)
- Genuinely useful and interesting to interact with
- Shareable — every AI-generated insight is a potential screenshot/tweet
- Model-agnostic (works with OpenAI, Anthropic, Google, Ollama/local models)

## Architecture

### Layer 1: Data Ingestion (from Shadowbroker)

Fork Shadowbroker wholesale. It provides:
- 60+ real-time OSINT data feeds already integrated
- MapLibre GL map rendering
- Next.js frontend
- FastAPI + Python backend
- Docker deployment
- All data sources are public and free (OpenSky, AIS, GDELT, N2YO, USGS, etc.)

Restyle/rebrand the UI to make it Palomar's own, but keep the data pipeline intact. The AGPL-3.0 license requires the derivative work to also be open source, which aligns with our goals.

### Layer 2: AI Intelligence Analyst (what we build)

This is a three-tier filtering system designed to keep costs near zero:

**Tier 1: Statistical Anomaly Detection (free, just code)**
- Establish baselines for each data domain (average military aircraft in a region, normal shipping traffic through a strait, typical earthquake frequency)
- Flag anything that deviates significantly from baseline (simple standard deviation)
- Apply rules: geofencing alerts, keyword matching on GDELT news events, velocity/heading changes in maritime data, unusual aircraft type in unusual location
- This filters out 95%+ of noise with zero API calls

**Tier 2: Cheap Model Triage (pennies per day)**
- Flagged anomalies from Tier 1 get passed to a cheap/fast model (Gemini Flash, GPT-4o-mini, or a local model via Ollama)
- Prompt: "Here are N anomalies detected in the last hour. Rate each 1-5 for genuine significance. Briefly explain why."
- Only a handful of API calls per hour
- This further filters down to genuinely interesting signals

**Tier 3: Full LLM Analysis (on demand)**
- Invoked only when:
  - Tier 2 flags something as high-signal (score 4-5)
  - A user asks a question through the conversational interface
- Uses a stronger model (Claude, GPT-4, etc.) for deep analysis
- Produces the "intelligence briefing" output
- Cross-references anomalies across domains (e.g., correlating unusual aircraft activity with GDELT news events in the same region)

### Layer 3: Conversational Interface

A chat interface (sidebar or overlay on the map) where users can:
- Ask "What's unusual right now?" and get a briefing
- Ask about specific regions: "What's happening near the Taiwan Strait?"
- Ask about specific data types: "Any unusual military aircraft activity in the last 24 hours?"
- Drill into specific anomalies the system has flagged
- The AI has access to the current state of all feeds plus a rolling context window of recent events

### Data Flow

```
60+ OSINT Feeds (Shadowbroker)
        │
        ▼
Tier 1: Statistical Anomaly Detection (Python, no API)
        │
        ▼ (only anomalies)
Tier 2: Cheap Model Triage (Gemini Flash / local model)
        │
        ▼ (only high-signal items)
Tier 3: Full LLM Analysis (Claude / GPT-4 / user choice)
        │
        ▼
Dashboard Display + Conversational Interface
```

## Tech Stack

- **Frontend:** Next.js (inherited from Shadowbroker), MapLibre GL for map rendering
- **Backend:** FastAPI + Python (inherited from Shadowbroker)
- **AI Layer:** Python, LiteLLM or similar for model-agnostic LLM calls
- **Deployment:** Docker Compose (self-hosted, runs locally)
- **Models:** Support multiple providers — OpenAI, Anthropic, Google, Ollama (local). User configures via .env
- **Database:** Whatever Shadowbroker already uses for state, plus potentially a lightweight vector store or SQLite for the AI context window

## Key Design Decisions

1. **Model-agnostic from day one.** Users should be able to use any LLM provider or run fully local with Ollama. This widens the audience massively.

2. **Cost-conscious architecture.** The tiered filtering system means running Palomar costs pennies per day, not hundreds of dollars. A user with just Ollama installed can run it for free.

3. **Self-hosted only for v1.** No hosted demo needed. Shadowbroker proved you can get massive traction with self-hosted only + good screenshots in the README.

4. **The AI should be proactive, not just reactive.** It shouldn't only answer questions — it should surface interesting findings unprompted. A notification/alert panel showing "Palomar noticed something" is key.

5. **AGPL-3.0 license** (required by Shadowbroker's license, and fine for our goals).

## README Structure

The README is the single most important artifact. It should be structured as:

1. **Project name + epigraph** — "Palomar" + the Calvino quote
2. **One-line description** — "Real-time OSINT with an AI analyst. 60+ live feeds. One brain."
3. **Hero screenshot or GIF** — The dashboard with the AI surfacing an interesting finding. This is what sells the project. Make it look incredible.
4. **"What does Palomar do?" section** — Brief explanation with examples of the kind of insights it surfaces. Show example AI outputs.
5. **Quick Start** — `git clone`, `docker compose up`, done. Must be under 5 minutes.
6. **Architecture diagram** — Clean visual showing the three-tier system
7. **Supported models** — List of all LLM providers supported
8. **Data sources** — List of all 60+ feeds inherited from Shadowbroker
9. **Configuration** — How to set up API keys, choose models, configure alerts
10. **Contributing** — How to add new anomaly detection rules, new data sources
11. **License** — AGPL-3.0

## v2 / Future Features (not for initial build)

- **MiroFish-style prediction:** When Palomar flags an interesting situation, offer a "Simulate what happens next" button that spins up a swarm intelligence simulation using OASIS (the engine behind MiroFish). This becomes its own second launch moment.
- **Alerting:** Push notifications (Telegram, Discord, email) when Palomar detects something significant
- **Historical analysis:** Store detected anomalies over time and let the AI analyze trends
- **Hosted demo:** A public instance with limited feeds for people to try without installing

## What to Build First

Priority order:
1. Fork and rebrand Shadowbroker (get it running as Palomar with new styling)
2. Build Tier 1 anomaly detection for 3-4 data domains (aircraft, GDELT/conflict, maritime, seismic)
3. Build Tier 2 cheap model triage
4. Build the conversational interface
5. Build Tier 3 deep analysis
6. Create compelling README with screenshots/GIFs
7. Prepare launch content (blog post / Twitter thread showing best AI findings)

## Launch Strategy

- **Primary target:** Hacker News. This is exactly the kind of project HN loves.
- **Secondary:** AI Twitter/X. Post a thread showing the AI in action with screenshots of real findings.
- **Tertiary:** Reddit — r/OSINT, r/selfhosted, r/artificial, r/LocalLLaMA
- **The hook:** Not "check out my new tool" but "I gave an OSINT dashboard an AI brain and here's what it found." Lead with the output, not the technology.
- **Every new model release** becomes a content event: "Here's how GPT-6 / Claude / Gemini performs as Palomar's analyst."

## Key References

- **Shadowbroker:** https://github.com/BigBodyCobain/Shadowbroker (also mirrored at https://gitlab.com/bigbodycobain/Shadowbroker)
- **Shadowbroker archived fork with improvements:** https://github.com/johan-martensson/Shadowbroker-archived
- **MiroFish (future v2 inspiration):** https://github.com/666ghj/MiroFish
- **OASIS simulation engine (for future v2):** From CAMEL-AI research community
- **Mr. Palomar by Italo Calvino** — the literary source for the name and philosophy
