# CSV Data Ingestion Pipeline

The ReconAI ingestion layer is responsible for transferring raw external CSV transaction reports into strongly typed, validated SQLAlchemy database models.

```text
CSV Source Files
       │
       ▼
[Schema Validation] ─── (Missing header columns fail immediately)
       │
       ▼
[Row Parsing & Typing] ─ (Decimals, ISO-8601 datetimes, Nullable conversions)
       │
       ▼
[In-Memory Deduplication] ─ (Duplicate primary keys detected pre-DB)
       │
       ▼
[Atomic Database Transaction] ─── (session.add_all -> commit / rollback)
       │
       ▼
Database Persistence