# Candidate Scoring & Ambiguity Resolution Strategy

The ReconAI Candidate Scoring Engine evaluates evidence strength between payments and prospective settlements when deterministic exact transaction IDs are missing or unlinked.

```text
Payment
   │
   ▼
Candidate Discovery (unlinked settlements sharing merchant & currency within time window)
   │
   ▼
Candidate Set
   │
   ▼
Feature / Evidence Evaluation
   ├── Amount Match (Weight: 40%)
   ├── Merchant Match (Weight: 25%)
   ├── Currency Match (Weight: 15%)
   └── Timestamp Proximity (Weight: 20%)
   │
   ▼
Deterministic Ranking (Score DESC, Settlement ID ASC)
   │
   ▼
Threshold & Ambiguity Decision Gate
   ├── Decisive Winner (Score ≥ 0.85, Margin ≥ 0.05) ──► MATCHED (MatchedBy.SCORED_CANDIDATE)
   ├── Ambiguous / Near-Tie (Margin < 0.05)          ──► AMBIGUOUS (Routes to AI Investigation)
   ├── Score Below Acceptance (< 0.85)               ──► UNRESOLVED / MISSING_SETTLEMENT
   └── Empty Candidate Set                           ──► MISSING_SETTLEMENT