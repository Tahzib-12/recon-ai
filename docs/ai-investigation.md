# AI-Powered Exception Investigation Engine

The ReconAI AI Investigation Engine assists human financial analysts by analyzing ambiguous reconciliation exceptions. It does not replace deterministic matching; rather, it investigates exceptions that rule-based systems cannot resolve with certainty.

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
                     Investigation?
                        /          \
                      NO            YES
                      ↓              ↓
               Final Result    Evidence Builder
                                      ↓
                               Evidence Package
                                      ↓
                               AI Investigator
                                      ↓
                            Structured AI Verdict
                                      ↓
                            Human Verification (Commit 8)