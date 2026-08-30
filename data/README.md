# Data Directory

This directory is reserved for storing synthetic financial datasets used during local development, testing, and evaluation of the ReconAI reconciliation engine.

## Security Notice
- **NO REAL CUSTOMER OR PRODUCTION DATA:** Real payment, settlement, banking, or customer personal identifiable information (PII) must **never** be placed in or committed to this repository.
- Use only generated synthetic datasets or publicly scrubbed sandbox data.

## Synthetic Dataset Generator
A reproducible, deterministic dataset generator is provided in `generate_dataset.py`.

### Generating the Sample Dataset
From the `data/` directory or project root:
```powershell
python data/generate_dataset.py