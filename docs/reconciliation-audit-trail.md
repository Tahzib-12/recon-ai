# Reconciliation Audit Trail & Decision Lineage

In financial reconciliation, an audit trail answers:
- **What happened to this transaction?**
- **Who made each decision (Deterministic software, AI, or Human reviewer)?**
- **What exact evidence existed at that point in time?**
- **What was the state transition?**

```text
                  ┌──────────────────────┐
                  │ Deterministic Engine │ ──► Audit: RECONCILIATION_COMPLETED (SYSTEM)
                  └──────────┬───────────┘
                             ↓
                  ┌──────────────────────┐
                  │  Candidate Scoring   │ ──► Audit: CANDIDATES_SCORED (SYSTEM)
                  └──────────┬───────────┘
                             ↓
                  ┌──────────────────────┐
                  │   AI Investigation   │ ──► Audit: INVESTIGATION_COMPLETED (AI)
                  └──────────┬───────────┘
                             ↓
                  ┌──────────────────────┐
                  │  Human Verification  │ ──► Audit: REVIEW_APPROVED / REJECTED (HUMAN)
                  └──────────┬───────────┘
                             ↓
                  ┌──────────────────────┐
                  │   Final Resolution   │ ──► Audit: CASE_RESOLVED (HUMAN/SYSTEM)
                  └──────────────────────┘