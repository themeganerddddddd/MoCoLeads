"use strict";

const $ = (selector) => document.querySelector(selector);
const dataBase = location.pathname.includes("/site/") ? "../data" : "./data";
const state = { records: [], filtered: [], metadata: null };
const techCategories = new Set(["Defense", "Defense Technology", "Space / Satellite", "Cybersecurity", "Artificial Intelligence / Data", "Software / IT", "Quantum", "Microelectronics / Semiconductor", "Advanced Communications", "Autonomous Systems / Drones", "Advanced Manufacturing"]);

function safe(value, fallback = "Not disclosed") { return value === null || value === undefined || value === "" ? fallback : String(value); }
function escapeHtml(value) { return safe(value, "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c])); }
function formatDate(value) {
  if (!value) return "Not disclosed";
  const date = new Date(`${value}T12:00:00Z`);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("en-US", {month:"short", day:"numeric", year:"numeric", timeZone:"UTC"}).format(date);
}
function formatValue(value) {
  if (value === null || value === undefined) return "Not disclosed";
  const abs = Math.abs(Number(value));
  for (const [limit, suffix] of [[1e9,"B"],[1e6,"M"],[1e3,"K"]]) if (abs >= limit) return `$${(value/limit).toFixed(abs >= limit*100 ? 0 : 1).replace(".0","")}${suffix}`;
  return new Intl.NumberFormat("en-US", {style:"currency", currency:"USD", maximumFractionDigits:0}).format(value);
}
function sourceLabel(source) {
  if (source?.source_type === "structured_award") return source?.name === "USAspending" ? "View USAspending Award" : "View Federal Award";
  if (source?.source_type === "retrieval_fallback") return "Retrieval provider";
  return "View Announcement";
}
function sourceLink(source, compact = false) {
  if (!source?.source_url) return "Not available";
  const compactLabel = source.source_type === "structured_award" ? "Federal award ↗" : source.source_type === "retrieval_fallback" ? "Retrieval provider ↗" : "Announcement ↗";
  const label = compact ? compactLabel : `${sourceLabel(source)} ↗`;
  return `<a class="source-link" href="${escapeHtml(source.source_url)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
}

async function loadData() {
  try {
    const [recordsResponse, metadataResponse] = await Promise.all([fetch(`${dataBase}/contracts.json`, {cache:"no-store"}), fetch(`${dataBase}/metadata.json`, {cache:"no-store"})]);
    if (!recordsResponse.ok || !metadataResponse.ok) throw new Error("Data files could not be loaded");
    state.records = await recordsResponse.json();
    state.metadata = await metadataResponse.json();
    setupMetadata(); populateSelects(); applyFilters();
  } catch (error) {
    $("#loading-state").hidden = true;
    $("#empty-state").hidden = false;
    $("#empty-state h3").textContent = "Award data is unavailable";
    $("#empty-state p").textContent = "Run the update pipeline or check the published data files, then refresh this page.";
    $("#result-count").textContent = "Could not load awards";
    $("#last-updated").textContent = "Unavailable";
    console.error(error);
  }
}

function setupMetadata() {
  const updated = state.metadata?.last_updated;
  $("#last-updated").textContent = updated ? `Updated ${new Intl.DateTimeFormat("en-US", {month:"long", day:"numeric", year:"numeric", hour:"numeric", minute:"2-digit", timeZoneName:"short"}).format(new Date(updated))}` : "Not yet updated";
  const status = state.metadata?.collector_status || {};
  const failures = Object.entries(status).filter(([,value]) => String(value).startsWith("failed") || value === "partial").map(([name]) => name === "war" ? "War.gov" : ["diu","darpa","sbir","sam"].includes(name) ? name.toUpperCase() : name.charAt(0).toUpperCase()+name.slice(1));
  if (failures.length) {
    $("#source-warning").hidden = false;
    $("#source-warning").textContent = `The latest update completed, but ${new Intl.ListFormat("en-US").format(failures)} could not be checked. Existing historical records remain available.`;
  }
  $("#download-csv").href = `${dataBase}/contracts.csv`;
  $("#download-json").href = `${dataBase}/contracts.json`;
}

function addOptions(selector, values) {
  const select = $(selector);
  [...new Set(values.filter(Boolean))].sort((a,b) => a.localeCompare(b)).forEach(value => select.add(new Option(value, value)));
}
function populateSelects() {
  addOptions("#category-filter", state.records.map(r => r.classification?.primary));
  addOptions("#agency-filter", state.records.map(r => r.award?.agency));
  addOptions("#company-filter", state.records.map(r => r.company?.canonical_name));
}

function cutoffDate(mode) {
  const latest = state.metadata?.last_updated ? new Date(state.metadata.last_updated) : new Date();
  if (mode === "all" || mode === "custom") return null;
  if (mode === "ytd") return new Date(Date.UTC(latest.getUTCFullYear(), 0, 1));
  const days = Number(mode); const cutoff = new Date(latest); cutoff.setUTCDate(cutoff.getUTCDate() - days); return cutoff;
}

function searchable(record) {
  return [record.company?.canonical_name, record.company?.legal_name, record.award?.description, record.award?.agency, record.award?.subagency, record.classification?.primary, ...(record.classification?.secondary || []), record.award?.contract_number, record.award?.award_id, record.location?.place_of_performance, ...(record.location?.work_locations || [])].join(" ").toLowerCase();
}
function applyFilters() {
  const query = $("#search").value.trim().toLowerCase();
  const dateMode = $("#date-filter").value;
  const cutoff = cutoffDate(dateMode);
  const from = $("#date-from").value ? new Date(`${$("#date-from").value}T00:00:00Z`) : null;
  const to = $("#date-to").value ? new Date(`${$("#date-to").value}T23:59:59Z`) : null;
  const category = $("#category-filter").value, agency = $("#agency-filter").value, company = $("#company-filter").value;
  const minAmount = Number($("#amount-filter").value), hq = $("#hq-filter").value;
  state.filtered = state.records.filter(record => {
    const valueDate = record.announcement_date || record.action_date;
    const date = valueDate ? new Date(`${valueDate}T12:00:00Z`) : null;
    const datePass = dateMode === "custom" ? (!from || (date && date >= from)) && (!to || (date && date <= to)) : !cutoff || (date && date >= cutoff);
    const hqStatus = record.company?.hq_status;
    const hqPass = hq === "all" || (hq === "strong" ? ["verified","strong"].includes(hqStatus) : hqStatus === "verified");
    return datePass && hqPass && (!query || searchable(record).includes(query)) && (!category || record.classification?.primary === category) && (!agency || record.award?.agency === agency) && (!company || record.company?.canonical_name === company) && (!minAmount || Number(record.award?.amount || 0) > minAmount);
  });
  sortRecords(); render();
}
function sortRecords() {
  const mode = $("#sort-filter").value;
  state.filtered.sort((a,b) => {
    if (mode === "newest" || mode === "oldest") { const diff = (a.announcement_date || a.action_date || "").localeCompare(b.announcement_date || b.action_date || ""); return mode === "newest" ? -diff : diff; }
    if (mode === "largest" || mode === "smallest") { const av = a.award?.amount ?? (mode === "largest" ? -Infinity : Infinity), bv = b.award?.amount ?? (mode === "largest" ? -Infinity : Infinity); return mode === "largest" ? bv-av : av-bv; }
    const field = mode === "company" ? [a.company?.canonical_name,b.company?.canonical_name] : [a.award?.agency,b.award?.agency];
    return safe(field[0],"").localeCompare(safe(field[1],""));
  });
}

function render() { renderMetrics(); renderRows(); }
function renderMetrics() {
  const total = state.filtered.reduce((sum,r) => sum + (Number(r.award?.amount) || 0), 0);
  const companies = new Set(state.filtered.map(r => r.company?.canonical_name).filter(Boolean)).size;
  const tech = state.filtered.filter(r => techCategories.has(r.classification?.primary)).length;
  $("#metric-awards").textContent = state.filtered.length.toLocaleString();
  $("#metric-value").textContent = formatValue(total);
  $("#metric-companies").textContent = companies.toLocaleString();
  $("#metric-tech").textContent = state.filtered.length ? `${Math.round(tech/state.filtered.length*100)}%` : "—";
}
function renderRows() {
  const tbody = $("#contract-rows"); tbody.replaceChildren(); $("#loading-state").hidden = true;
  $("#empty-state").hidden = state.filtered.length > 0;
  $("#result-count").textContent = `${state.filtered.length.toLocaleString()} ${state.filtered.length === 1 ? "award" : "awards"}`;
  const fragment = document.createDocumentFragment();
  state.filtered.forEach(record => {
    const row = $("#row-template").content.firstElementChild.cloneNode(true);
    const cell = name => row.querySelector(`[data-cell="${name}"]`);
    cell("date").textContent = formatDate(record.announcement_date || record.action_date);
    cell("company").innerHTML = `<span class="company-name">${escapeHtml(record.company?.canonical_name)}</span><span class="hq-mini">HQ: ${escapeHtml([record.company?.hq_city, record.company?.hq_state].filter(Boolean).join(", ") || "Under review")}</span>`;
    cell("amount").textContent = formatValue(record.award?.amount);
    cell("agency").textContent = safe(record.award?.subagency || record.award?.agency);
    cell("category").innerHTML = `<span class="category-tag">${escapeHtml(record.classification?.primary)}</span>`;
    cell("description").innerHTML = `<span class="description-cell">${escapeHtml(record.award?.description)}</span>`;
    cell("location").textContent = safe(record.location?.place_of_performance || record.location?.work_locations?.join("; "));
    cell("contract").textContent = safe(record.award?.contract_number || record.award?.award_id, "—");
    cell("source").innerHTML = sourceLink(record.source, true);
    row.addEventListener("click", event => { if (!event.target.closest("a")) openDetail(record); });
    row.addEventListener("keydown", event => { if ((event.key === "Enter" || event.key === " ") && !event.target.closest("a")) { event.preventDefault(); openDetail(record); } });
    fragment.append(row);
  });
  tbody.append(fragment);
}

function detailField(label, value, html = false) { return `<div class="detail-field"><dt>${escapeHtml(label)}</dt><dd>${html ? value : escapeHtml(safe(value))}</dd></div>`; }
function openDetail(r) {
  const sources = (r.sources?.length ? r.sources : [r.source]).filter(s => s?.source_url);
  const hq = [r.company?.hq_city, r.company?.hq_state].filter(Boolean).join(", ") || "Under review";
  $("#detail-content").innerHTML = `<div class="detail-body">
    <div class="detail-title-row"><div><p class="section-kicker">${escapeHtml(r.classification?.primary)}</p><h2 id="detail-title">${escapeHtml(r.company?.canonical_name)}</h2><p>Headquarters: ${escapeHtml(hq)} · <span class="confidence">${escapeHtml(r.company?.hq_status || "needs review")}</span></p></div><div class="detail-amount">${formatValue(r.award?.amount)}</div></div>
    <dl class="detail-grid">
      ${detailField("Ultimate parent", r.company?.ultimate_parent)}${detailField("Agency", r.award?.agency)}${detailField("Subagency", r.award?.subagency)}
      ${detailField("Contract number", r.award?.contract_number)}${detailField("Award ID", r.award?.award_id)}${detailField("Award type", r.award?.award_type)}
      ${detailField("Announcement date", formatDate(r.announcement_date))}${detailField("Action date", formatDate(r.action_date))}${detailField("Expected completion", r.award?.expected_completion)}
      ${detailField("NAICS", r.award?.naics)}${detailField("PSC", r.award?.psc)}${detailField("Place of performance", r.location?.place_of_performance || r.location?.work_locations?.join("; "))}
    </dl>
    <div class="detail-description"><h3>What it was for</h3><p>${escapeHtml(r.award?.description)}</p></div>
    <div class="source-list"><h3>Sources and retrieval provenance</h3><p>The official record remains primary; retrieval-provider links document fallback provenance.</p><div class="source-list-links">${sources.map(source => sourceLink(source)).join("")}</div></div>
  </div>`;
  $("#detail-dialog").showModal();
}

function exportFilteredCsv() {
  const headers = ["Date","Company","HQ status","Amount","Agency","Category","Description","Work location","Contract number","Source URL"];
  const rows = state.filtered.map(r => [r.announcement_date || r.action_date, r.company?.canonical_name, r.company?.hq_status, r.award?.amount, r.award?.agency, r.classification?.primary, r.award?.description, r.location?.place_of_performance, r.award?.contract_number || r.award?.award_id, r.source?.source_url]);
  const csv = [headers, ...rows].map(row => row.map(value => `"${safe(value,"").replaceAll('"','""')}"`).join(",")).join("\r\n");
  const link = Object.assign(document.createElement("a"), {href: URL.createObjectURL(new Blob([csv], {type:"text/csv;charset=utf-8"})), download:"moco-federal-contracts-filtered.csv"});
  link.click(); URL.revokeObjectURL(link.href);
}
function clearFilters() {
  $("#search").value = ""; $("#date-filter").value = "30"; $("#category-filter").value = ""; $("#agency-filter").value = ""; $("#company-filter").value = ""; $("#amount-filter").value = "0"; $("#hq-filter").value = "strong"; $("#sort-filter").value = "newest"; $("#custom-dates").hidden = true; applyFilters();
}

document.addEventListener("DOMContentLoaded", () => {
  ["#search","#date-from","#date-to"].forEach(id => $(id).addEventListener("input", applyFilters));
  ["#date-filter","#category-filter","#agency-filter","#company-filter","#amount-filter","#hq-filter","#sort-filter"].forEach(id => $(id).addEventListener("change", () => { if (id === "#date-filter") $("#custom-dates").hidden = $(id).value !== "custom"; applyFilters(); }));
  $("#clear-filters").addEventListener("click", clearFilters); $("#download-filtered").addEventListener("click", exportFilteredCsv);
  $("#dialog-close").addEventListener("click", () => $("#detail-dialog").close());
  $("#detail-dialog").addEventListener("click", event => { if (event.target === $("#detail-dialog")) $("#detail-dialog").close(); });
  document.addEventListener("keydown", event => { if (event.key === "/" && !/input|textarea|select/i.test(document.activeElement.tagName)) { event.preventDefault(); $("#search").focus(); } });
  loadData();
});
