/**
 * ReconAI - Financial Operations Dashboard Client.
 * Connects directly to the dashboard API endpoints without client-side business logic.
 */

// State tracking
let currentStatus = "";
let currentSearch = "";
let currentMerchant = "";
let currentLimit = 15;
let currentOffset = 0;
let totalCases = 0;
let searchDebounceTimeout = null;

// DOM Elements
const totalCasesEl = document.getElementById("metric-total-cases");
const totalSubtextEl = document.getElementById("metric-subtext");
const matchRateEl = document.getElementById("metric-match-rate");
const exceptionsEl = document.getElementById("metric-exceptions");
const exceptionsSubtextEl = document.getElementById("metric-exception-subtext");
const statusChipsEl = document.getElementById("status-chips");
const searchInputEl = document.getElementById("search-input");
const statusSelectEl = document.getElementById("status-filter-select");
const merchantSelectEl = document.getElementById("merchant-filter-select");
const casesTableBodyEl = document.getElementById("cases-table-body");
const paginationInfoEl = document.getElementById("pagination-info");
const btnPrevPageEl = document.getElementById("btn-prev-page");
const btnNextPageEl = document.getElementById("btn-next-page");

// Modal Elements
const modalOverlayEl = document.getElementById("case-modal-overlay");
const modalTitleEl = document.getElementById("modal-case-title");
const overviewGridEl = document.getElementById("modal-overview-grid");
const candidatesSectionEl = document.getElementById("modal-candidates-section");
const candidatesListEl = document.getElementById("modal-candidates-list");
const aiSectionEl = document.getElementById("modal-ai-section");
const aiContentEl = document.getElementById("modal-ai-content");
const reviewSectionEl = document.getElementById("modal-review-section");
const reviewContentEl = document.getElementById("modal-review-content");
const auditTimelineEl = document.getElementById("modal-audit-timeline");

/**
 * Fetch and render high-level reconciliation summary.
 */
async function loadSummary() {
  try {
    const res = await fetch("/dashboard/summary");
    if (!res.ok) throw new Error("Failed to fetch dashboard summary.");
    const data = await res.json();
    renderSummary(data);
    renderStatusChips(data.status_counts, data.total_cases);
  } catch (err) {
    console.error(err);
    totalCasesEl.innerText = "—";
    totalSubtextEl.innerText = "Error loading summary metrics";
  }
}

/**
 * Render summary metric values returned by API.
 */
function renderSummary(data) {
  totalCasesEl.innerText = data.total_cases;
  totalSubtextEl.innerText = `${data.total_payments} Payments | ${data.total_settlements} Settlements | ${data.total_refunds} Refunds`;
  matchRateEl.innerText = `${data.match_rate_pct}%`;
  exceptionsEl.innerText = data.exception_cases;
  exceptionsSubtextEl.innerText = `${data.exception_rate_pct}% Exception Rate`;
}

/**
 * Render clickable status filter chips with counts.
 */
function renderStatusChips(statusCounts, total) {
  statusChipsEl.innerHTML = "";

  const allChip = document.createElement("div");
  allChip.className = `status-chip ${currentStatus === "" ? "active" : ""}`;
  allChip.innerHTML = `ALL <span class="status-chip-count">${total}</span>`;
  allChip.onclick = () => selectStatus("");
  statusChipsEl.appendChild(allChip);

  for (const [st, count] of Object.entries(statusCounts)) {
    const chip = document.createElement("div");
    chip.className = `status-chip ${currentStatus === st ? "active" : ""}`;
    chip.innerHTML = `${st} <span class="status-chip-count">${count}</span>`;
    chip.onclick = () => selectStatus(st);
    statusChipsEl.appendChild(chip);
  }
}

/**
 * Fetch and render paginated reconciliation cases matching filters.
 */
async function loadCases() {
  casesTableBodyEl.innerHTML = `<tr><td colspan="9" class="state-box">Loading reconciliation cases...</td></tr>`;

  try {
    const params = new URLSearchParams();
    params.set("limit", currentLimit);
    params.set("offset", currentOffset);

    if (currentStatus) params.set("status", currentStatus);
    if (currentSearch) params.set("search", currentSearch);
    if (currentMerchant) params.set("merchant_id", currentMerchant);

    const res = await fetch(`/dashboard/cases?${params.toString()}`);
    if (!res.ok) throw new Error("Failed to load cases.");
    const data = await res.json();

    totalCases = data.total;
    renderCases(data.cases);
    updatePaginationControls();
  } catch (err) {
    console.error(err);
    casesTableBodyEl.innerHTML = `<tr><td colspan="9" class="state-box text-danger">Unable to load reconciliation cases.</td></tr>`;
  }
}

/**
 * Render table rows for reconciliation cases.
 */
function renderCases(cases) {
  if (!cases || cases.length === 0) {
    casesTableBodyEl.innerHTML = `<tr><td colspan="9" class="state-box">No reconciliation cases found matching criteria.</td></tr>`;
    return;
  }

  casesTableBodyEl.innerHTML = cases
    .map((c) => {
      const pAmount = c.payment_amount ? `₹${c.payment_amount}` : "—";
      const sAmount = c.settled_amount ? `₹${c.settled_amount}` : "—";
      const diffVal = c.difference && c.difference !== "0.00" ? `₹${c.difference}` : "—";
      const diffClass = c.difference && c.difference !== "0.00" ? "text-danger" : "text-muted";
      const merchant = c.merchant_id || "—";
      const candBadge =
        c.candidate_count > 0
          ? `<span class="badge badge-purple">${c.candidate_count} Candidates</span>`
          : "—";

      return `
      <tr onclick="loadCaseDetail('${c.case_id}')">
        <td class="mono-cell" style="color: var(--primary-blue); font-weight: 600;">${c.case_id}</td>
        <td>${getStatusBadge(c.reconciliation_status)}</td>
        <td class="mono-cell">${pAmount}</td>
        <td class="mono-cell">${sAmount}</td>
        <td class="mono-cell ${diffClass}">${diffVal}</td>
        <td class="mono-cell">${merchant}</td>
        <td>${candBadge}</td>
        <td><span class="badge ${c.review_status === "RESOLVED" ? "badge-success" : "badge-warning"}">${c.review_status}</span></td>
        <td><button class="btn-page" style="padding: 3px 8px; font-size: 11px;">Inspect</button></td>
      </tr>
    `;
    })
    .join("");
}

/**
 * Return semantic visual status badge HTML.
 */
function getStatusBadge(status) {
  if (status === "MATCHED" || status === "MATCHED_WITH_TOLERANCE" || status === "REFUNDED") {
    return `<span class="badge badge-success">${status}</span>`;
  }
  if (status === "AMBIGUOUS" || status === "DUPLICATE_SETTLEMENT") {
    return `<span class="badge badge-purple">${status}</span>`;
  }
  if (status === "AMOUNT_MISMATCH" || status === "PARTIAL_SETTLEMENT") {
    return `<span class="badge badge-warning">${status}</span>`;
  }
  return `<span class="badge badge-danger">${status}</span>`;
}

/**
 * Fetch and render complete 360-degree case details.
 */
async function loadCaseDetail(caseId) {
  try {
    modalTitleEl.innerText = `Case Details: ${caseId}`;
    overviewGridEl.innerHTML = `<div class="state-box">Loading case detail...</div>`;
    modalOverlayEl.style.display = "flex";

    const res = await fetch(`/dashboard/cases/${encodeURIComponent(caseId)}`);
    if (!res.ok) throw new Error("Case detail not found.");
    const data = await res.json();
    renderCaseDetail(data);
  } catch (err) {
    console.error(err);
    overviewGridEl.innerHTML = `<div class="state-box text-danger">Failed to load details for case ${caseId}.</div>`;
  }
}

/**
 * Render all panels of the case detail view.
 */
function renderCaseDetail(data) {
  // Case Overview Grid
  const payment = data.payment || {};
  const settlement = data.settlement || {};

  overviewGridEl.innerHTML = `
    <div class="info-item"><div class="info-item-label">Status</div><div class="info-item-val">${getStatusBadge(data.reconciliation_status)}</div></div>
    <div class="info-item"><div class="info-item-label">Reason Code</div><div class="info-item-val">${data.reason_code}</div></div>
    <div class="info-item"><div class="info-item-label">Matched By</div><div class="info-item-val">${data.matched_by}</div></div>
    <div class="info-item"><div class="info-item-label">Payment Amount</div><div class="info-item-val">${data.payment_amount ? "₹" + data.payment_amount : "—"}</div></div>
    <div class="info-item"><div class="info-item-label">Settled Amount</div><div class="info-item-val">${data.settled_amount ? "₹" + data.settled_amount : "—"}</div></div>
    <div class="info-item"><div class="info-item-label">Difference</div><div class="info-item-val ${data.difference ? "text-danger" : ""}">${data.difference ? "₹" + data.difference : "—"}</div></div>
    <div class="info-item"><div class="info-item-label">Merchant ID</div><div class="info-item-val">${payment.merchant_id || settlement.merchant_id || "—"}</div></div>
    <div class="info-item"><div class="info-item-label">Customer ID</div><div class="info-item-val">${payment.customer_id || "—"}</div></div>
    <div class="info-item"><div class="info-item-label">Currency</div><div class="info-item-val">${payment.currency || settlement.currency || "—"}</div></div>
  `;

  // Candidate Scoring Section
  if (data.candidates && data.candidates.length > 0) {
    candidatesSectionEl.style.display = "block";
    candidatesListEl.innerHTML = data.candidates
      .map(
        (c) => `
        <div style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 6px; padding: 12px; margin-bottom: 8px;">
          <div style="display: flex; justify-content: space-between; font-weight: 600;">
            <span class="mono-cell" style="color: var(--primary-blue);">${c.settlement_id}</span>
            <span class="mono-cell" style="color: var(--status-purple);">Evidence Score: ${c.total_score}</span>
          </div>
          <div style="color: var(--text-secondary); font-size: 11px; margin-top: 6px;">
            Amount Match: ${c.amount_score} | Merchant: ${c.merchant_score} | Currency: ${c.currency_score} | Timestamp Proximity: ${c.timestamp_score}
          </div>
        </div>
      `
      )
      .join("");
  } else {
    candidatesSectionEl.style.display = "none";
  }

  // AI Investigation Section
  if (data.ai_investigation) {
    aiSectionEl.style.display = "block";
    const ai = data.ai_investigation;
    aiContentEl.innerHTML = `
      <div style="display: flex; gap: 10px; margin-bottom: 8px;">
        <span class="badge badge-purple">${ai.classification}</span>
        <span class="badge badge-success">${ai.recommended_action}</span>
      </div>
      <div style="background: var(--bg-card); padding: 10px 14px; border-radius: 6px; border-left: 3px solid var(--status-purple); margin-bottom: 8px;">
        ${ai.summary}
      </div>
      <div style="font-size: 11px; color: var(--text-secondary);">
        <strong>Observed Facts:</strong> ${ai.observed_facts.join("; ")}
      </div>
    `;
  } else {
    aiSectionEl.style.display = "none";
  }

  // Human Review Section
  if (data.human_review) {
    reviewSectionEl.style.display = "block";
    const rev = data.human_review;
    reviewContentEl.innerHTML = `
      <div class="info-grid">
        <div class="info-item"><div class="info-item-label">Review Status</div><div class="info-item-val">${rev.review_status}</div></div>
        <div class="info-item"><div class="info-item-label">Reviewer</div><div class="info-item-val">${rev.reviewer_id || "Unassigned"}</div></div>
        <div class="info-item"><div class="info-item-label">Decision</div><div class="info-item-val">${rev.decision || "Pending"}</div></div>
        <div class="info-item"><div class="info-item-label">Final Resolution</div><div class="info-item-val">${rev.final_resolution_status || "In Progress"}</div></div>
      </div>
      ${rev.notes ? `<div style="margin-top: 8px; font-size: 12px; color: var(--text-secondary);"><strong>Reviewer Notes:</strong> ${rev.notes}</div>` : ""}
    `;
  } else {
    reviewSectionEl.style.display = "none";
  }

  // Chronological Audit Timeline
  if (data.audit_timeline && data.audit_timeline.length > 0) {
    auditTimelineEl.innerHTML = data.audit_timeline
      .map(
        (ev) => `
        <div class="timeline-event">
          <div class="timeline-meta">${ev.timestamp} · [${ev.actor_type}] ${ev.actor_id}</div>
          <div class="timeline-desc"><strong>${ev.event_type}</strong>: ${ev.description}</div>
        </div>
      `
      )
      .join("");
  } else {
    auditTimelineEl.innerHTML = `<div class="state-box">No audit events recorded for this case.</div>`;
  }
}

/**
 * Close modal and restore focus.
 */
function closeCaseDetail() {
  modalOverlayEl.style.display = "none";
}

/**
 * Filter handlers
 */
function selectStatus(status) {
  currentStatus = status;
  currentOffset = 0;
  statusSelectEl.value = status;
  document.querySelectorAll(".status-chip").forEach((c) => c.classList.remove("active"));
  loadCases();
}

function handleStatusFilterChange(e) {
  currentStatus = e.target.value;
  currentOffset = 0;
  loadCases();
}

function handleMerchantFilterChange(e) {
  currentMerchant = e.target.value;
  currentOffset = 0;
  loadCases();
}

function handleSearchInput(e) {
  clearTimeout(searchDebounceTimeout);
  searchDebounceTimeout = setTimeout(() => {
    currentSearch = e.target.value.trim();
    currentOffset = 0;
    loadCases();
  }, 250);
}

/**
 * Pagination handlers
 */
function updatePaginationControls() {
  const start = totalCases === 0 ? 0 : currentOffset + 1;
  const end = Math.min(currentOffset + currentLimit, totalCases);
  paginationInfoEl.innerText = `Showing ${start}–${end} of ${totalCases} cases`;

  btnPrevPageEl.disabled = currentOffset <= 0;
  btnNextPageEl.disabled = currentOffset + currentLimit >= totalCases;
}

function handlePrevPage() {
  if (currentOffset > 0) {
    currentOffset = Math.max(0, currentOffset - currentLimit);
    loadCases();
  }
}

function handleNextPage() {
  if (currentOffset + currentLimit < totalCases) {
    currentOffset += currentLimit;
    loadCases();
  }
}

// Attach Event Listeners
searchInputEl.addEventListener("input", handleSearchInput);
statusSelectEl.addEventListener("change", handleStatusFilterChange);
merchantSelectEl.addEventListener("change", handleMerchantFilterChange);
btnPrevPageEl.addEventListener("click", handlePrevPage);
btnNextPageEl.addEventListener("click", handleNextPage);

// Initial Load
loadSummary();
loadCases();