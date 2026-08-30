
---

#### `3. docs/reconciliation-cases.md` (New)
```markdown
# Reconciliation Scenarios & Evaluation Specifications

ReconAI generates synthetic data across 13 core financial reconciliation scenarios. This document details each scenario, its generated records, expected resolution behavior, and architectural significance.

---

## 1. `PERFECT_MATCH`
* **Description:** Ideal transaction where payment and settlement share matching transaction IDs, amounts, currencies, and timestamps within the standard settlement window ($T+1$/$T+2$).
* **Generated Records:** 1 `Payment`, 1 `Settlement` (with matching `transaction_id` and amount).
* **Expected Outcome:** `MATCHED`.
* **System Action:** Deterministic matching engine instantly closes the reconciliation. Zero candidate scoring or AI intervention required.

---

## 2. `FEE_DISCREPANCY`
* **Description:** The merchant is credited less than the gross customer transaction due to Merchant Discount Rate (MDR) or interchange processing fees (e.g., 2%–3%).
* **Generated Records:** 1 `Payment` (₹1,000.00), 1 `Settlement` (₹971.00, matching `transaction_id`).
* **Expected Outcome:** `AMOUNT_MISMATCH`.
* **System Action:** Flagged by deterministic matcher due to amount difference. AI / rules engine investigates whether the difference correlates to standard fee schedules before flagging for human sign-off.

---

## 3. `MISSING_TRANSACTION_ID`
* **Description:** The acquiring bank or payment processor omitted the internal `transaction_id` from the settlement report.
* **Generated Records:** 1 `Payment`, 1 `Settlement` (with `transaction_id = ""` / `NULL`, but identical amount, merchant, and close timestamp).
* **Expected Outcome:** `CANDIDATE_MATCH`.
* **System Action:** Deterministic matcher cannot link by ID. Candidate scoring calculates a probabilistic similarity score based on merchant, amount, currency, and time proximity.

---

## 4. `MISSING_SETTLEMENT`
* **Description:** An internal payment succeeded, but no corresponding settlement payout has arrived from the processor.
* **Generated Records:** 1 `Payment`, 0 `Settlements`.
* **Expected Outcome:** `MISSING_SETTLEMENT`.
* **System Action:** Flagged as an open/unsettled item. Tracked against SLA aging thresholds before triggering an inquiry.

---

## 5. `ORPHAN_SETTLEMENT`
* **Description:** A bank settlement credit appears on the bank statement with no corresponding internal order or payment record.
* **Generated Records:** 0 `Payments`, 1 `Settlement` (with unknown reference ID).
* **Expected Outcome:** `ORPHAN_SETTLEMENT`.
* **System Action:** Flagged as unallocated funds or phantom credit. Requires ledger investigation.

---

## 6. `DELAYED_SETTLEMENT`
* **Description:** Payment and settlement match on all fields, but the settlement arrived significantly later than the standard settlement window (e.g., 6–14 days later).
* **Generated Records:** 1 `Payment`, 1 `Settlement` (with large timestamp delta).
* **Expected Outcome:** `DELAYED_SETTLEMENT`.
* **System Action:** Resolved as matched, but tagged with a delayed settlement warning for processor SLA tracking.

---

## 7. `PARTIAL_SETTLEMENT`
* **Description:** The payment processor settled only a portion of the total transaction amount (e.g., ₹6,000 settled of a ₹10,000 payment).
* **Generated Records:** 1 `Payment` (₹10,000.00), 1 `Settlement` (₹6,000.00, status `PARTIALLY_SETTLED`).
* **Expected Outcome:** `PARTIAL_SETTLEMENT`.
* **System Action:** Flagged for tranche reconciliation to track remaining pending balances.

---

## 8. `DUPLICATE_SETTLEMENT`
* **Description:** Two distinct settlement records are submitted for the same single customer payment.
* **Generated Records:** 1 `Payment`, 2 distinct `Settlements` (each referencing the same `transaction_id`).
* **Expected Outcome:** `DUPLICATE_SETTLEMENT`.
* **System Action:** Exception investigation flags potential double payout or duplicate batch ingestion.

---

## 9. `FULL_REFUND`
* **Description:** Customer returned the item or cancelled the order, resulting in a full refund of the original payment amount.
* **Generated Records:** 1 `Payment` (₹4,000.00), 1 `Settlement` (₹4,000.00), 1 `Refund` (₹4,000.00).
* **Expected Outcome:** `FULL_REFUND`.
* **System Action:** The system resolves the complete 3-way lifecycle (`PAID -> SETTLED -> FULL_REFUND`) balancing the net merchant position to ₹0.00.

---

## 10. `PARTIAL_REFUND`
* **Description:** A partial return or partial credit was issued against a settled transaction.
* **Generated Records:** 1 `Payment` (₹5,000.00), 1 `Settlement` (₹5,000.00), 1 `Refund` (₹2,000.00).
* **Expected Outcome:** `PARTIAL_REFUND`.
* **System Action:** Net settled position is reconciled to ₹3,000.00 with the active refund link.

---

## 11. `ROUNDING_DIFFERENCE`
* **Description:** Tiny 1-paisa (₹0.01) rounding discrepancy caused by tax computation or fractional currency conversions.
* **Generated Records:** 1 `Payment` (₹1,000.00), 1 `Settlement` (₹999.99 or ₹1,000.01).
* **Expected Outcome:** `AMOUNT_MISMATCH`.
* **System Action:** Identified by rule policies as falling within acceptable penny-rounding tolerance thresholds.

---

## 12. `AMBIGUOUS_CANDIDATES`
* **Description:** Multiple settlement records exist for the same merchant with identical amounts and proximate timestamps, with neither carrying an internal transaction ID.
* **Generated Records:** 1 `Payment`, 2 plausible unlinked `Settlements`.
* **Expected Outcome:** `AMBIGUOUS`.
* **System Action:** Candidate scoring identifies multiple candidates with tied confidence scores. The system refuses to guess and routes the case to `HUMAN_REVIEW`.

---

## 13. `UNRESOLVED`
* **Description:** Inconclusive records with missing gateway status and no matching settlement records.
* **Generated Records:** 1 `Payment` (status `PENDING_GATEWAY_RESPONSE`), 0 `Settlements`.
* **Expected Outcome:** `UNRESOLVED`.
* **System Action:** Escalated as an open operational exception.