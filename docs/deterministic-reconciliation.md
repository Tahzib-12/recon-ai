# Deterministic Reconciliation Engine

The ReconAI deterministic reconciliation engine resolves financial transactions using explicit, auditable rules without relying on machine learning or probabilistic heuristics.

```text
Payments / Settlements / Refunds
               │
               ▼
[Hash Index Construction] ──── O(P + S + R) in-memory lookups
               │
               ▼
[Stage 1: Exact ID Lookup] ─── Exact transaction_id matching
               │
               ▼
[Stage 2: Fallback Candidates]  Unlinked settlements (tx_id = NULL)
               │               (Matched via merchant, currency, amount, time)
               │
               ▼
[Stage 3: Amount, Tolerance & Lifecycle]
       ├── Match / Tolerance (≤ 0.01)
       ├── Fee / Discrepancy Detection
       ├── Duplicate Detection (Multiple exact settlements)
       └── Refund Balancing (Full & Partial refunds)
               │
               ▼
[Stage 4: Reverse Scan] ────── Unlinked settlements flagged as ORPHAN
               │
               ▼
Machine-Readable Reconciliation Results