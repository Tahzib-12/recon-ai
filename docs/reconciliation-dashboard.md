# Reconciliation Dashboard & API

The ReconAI Dashboard provides financial operations teams with a complete control center to monitor health metrics, inspect exception queues, review candidate match evidence, inspect advisory AI verdicts, and track chronological audit history.

```text
       Browser UI (HTML5 / Vanilla SPA)
                     │
                     ▼
           FastAPI Backend Router
          (/api/dashboard/summary, /cases, /cases/{case_id})
                     │
                     ▼
      Reconciliation & Audit Services
                     │
                     ▼
       Persistent SQLite / Postgres DB