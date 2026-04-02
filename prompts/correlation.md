# Cross-Domain Correlation Prompt

<!--
Used by Tier 3 to find connections between anomalies across different data domains.
-->

You are analyzing OSINT anomalies from multiple domains to identify potential connections. Your task is to find meaningful correlations — not forced associations.

## Anomalies by domain:

### Aircraft
{aircraft_anomalies}

### Maritime
{maritime_anomalies}

### Seismic
{seismic_anomalies}

### GDELT / Conflict
{gdelt_anomalies}

## Instructions

1. Identify any anomalies that are **geographically proximate** (within ~100km) and **temporally proximate** (within ~6 hours).
2. For each potential correlation, assess whether the connection is:
   - **Likely meaningful**: Clear logical relationship (e.g., military aircraft surge + elevated conflict reporting in same region)
   - **Possibly meaningful**: Temporal/spatial overlap but unclear causal link
   - **Coincidental**: No logical connection despite proximity
3. Only report correlations rated "likely" or "possibly" meaningful.

Respond in JSON format:
```json
[
  {
    "domains": ["aircraft", "gdelt"],
    "anomaly_ids": ["...", "..."],
    "relationship": "likely_meaningful",
    "explanation": "...",
    "region": "...",
    "time_window": "..."
  }
]
```

Be conservative. Most co-occurring anomalies are coincidental. Only flag correlations with a clear analytical rationale.
