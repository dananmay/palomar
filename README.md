# Palomar

Real-time OSINT platform with AI intelligence analysis. Fork of [Shadowbroker](https://github.com/BigBodyCobain/Shadowbroker) with a three-tier AI layer for anomaly detection, triage, and deep analysis.

## Quick start

```bash
cp .env.example .env
# Add API keys (optional — the dashboard works without them, AI features require at least one LLM key)
docker compose up
```

Frontend: http://localhost:3000
Backend API: http://localhost:8000

## License

AGPL-3.0 (inherited from upstream)
