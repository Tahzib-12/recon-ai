# Verification & Human Review Workflow

ReconAI enforces an explicit hierarchy of decision authority:
1. **Deterministic Rules:** Settle exact matches and validated tolerances.
2. **Candidate Scoring:** Discovers plausible candidate settlements with explainable feature weights.
3. **AI Investigation:** Analyzes exceptions and offers probabilistic findings and advisory recommendations.
4. **Human Verification (Authoritative):** A human investigator evaluates the full evidence lineage and makes the final, binding business decision.

```text
                  ┌──────────────────────┐
                  │    Financial Data    │
                  └──────────┬───────────┘
                             ↓
                  ┌──────────────────────┐
                  │ Deterministic Engine │
                  └──────────┬───────────┘
                             ↓
                  ┌──────────────────────┐
                  │  Candidate Scoring   │
                  └──────────┬───────────┘
                             ↓
                  ┌──────────────────────┐
                  │   AI Investigation   │
                  │      (Advisory)      │
                  └──────────┬───────────┘
                             ↓
                  ┌──────────────────────┐
                  │  Human Verification  │
                  │    (Authoritative)   │
                  └──────────┬───────────┘
                             ↓
                  ┌──────────────────────┐
                  │   Final Resolution   │
                  └──────────────────────┘