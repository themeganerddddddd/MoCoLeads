"use strict";

const $ = (selector) => document.querySelector(selector);
const dataBase = location.pathname.includes("/site/") ? "../data" : "./data";
const state = { records: [], filtered: [], metadata: null, loadAttempts: [], activeView: "moco" };
const techCategories = new Set(["Defense", "Defense Technology", "Space / Satellite", "Cybersecurity", "Artificial Intelligence / Data", "Software / IT", "Quantum", "Microelectronics / Semiconductor", "Advanced Communications", "Autonomous Systems / Drones", "Advanced Manufacturing"]);
const qualifiedStatuses = new Set(["verified", "strong", "local_entity"]);

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

function mocoStatusLabel(status) {
  return ({verified:"Verified headquarters", strong:"Strong headquarters evidence", local_entity:"Local legal entity", needs_review:"Needs review", not_moco:"Not a Montgomery County entity"})[status] || safe(status, "Needs review");
}
function mocoBasisLabel(basis) {
  return ({verified_hq:"Verified headquarters", verified_local_legal_entity:"Verified local legal entity", federal_recipient_address:"Federal recipient address", manual_registry:"Manual registry review"})[basis] || safe(basis, "Not documented").replaceAll("_", " ");
}
function viewRecords() { return MarketView.recordsForView(state.records, state.activeView); }

async function fetchJson(url, label) {
  const attempt = {label, url, status: null, detail: null};
  state.loadAttempts.push(attempt);
  try {
    const response = await fetch(url, {cache:"no-store"});
    attempt.status = response.status;
    attempt.detail = `${response.status} ${response.statusText || (response.ok ? "OK" : "Request failed")}`.trim();
    if (!response.ok) throw new Error(attempt.detail);
    try { return await response.json(); }
    catch (error) { attempt.detail = `HTTP ${response.status}; invalid JSON: ${error.message}`; throw error; }
  } catch (error) {
    if (attempt.status === null) attempt.detail = `${error.name || "Error"}: ${error.message || error}`;
    throw error;
  }
}

async function loadData() {
  state.loadAttempts = [];
  $("#load-diagnostics").hidden = true;
  $("#empty-state").hidden = true;
  $("#loading-state").hidden = false;
  $("#result-count").textContent = "Loading awards…";
  try {
    const results = await Promise.allSettled([
      fetchJson(`${dataBase}/contracts.json`, "Contract records"),
      fetchJson(`${dataBase}/metadata.json`, "Update metadata"),
    ]);
    const failure = results.find(result => result.status === "rejected");
    if (failure) throw failure.reason;
    state.records = results[0].value;
    state.metadata = results[1].value;
    setupMetadata(); populateSelects(); applyFilters();
  } catch (error) {
    $("#loading-state").hidden = true;
    $("#empty-state").hidden = true;
    $("#load-diagnostics").hidden = false;
    const list = $("#load-diagnostics-list");
    list.replaceChildren(...state.loadAttempts.map(attempt => {
      const item = document.createElement("li");
      const code = document.createElement("code"); code.textContent = attempt.url;
      const detail = document.createElement("span"); detail.textContent = `${attempt.label}: ${attempt.detail || "No response details"}`;
      item.append(code, detail); return item;
    }));
    $("#result-count").textContent = "Could not load awards";
    $("#last-updated").textContent = "Data load failed";
    console.error(error);
  }
}

function setupMetadata() {
  $("#source-warning").hidden = true;
  const updated = state.metadata?.last_updated;
  const updateLabel = updated ? new Intl.DateTimeFormat("en-US", {month:"short", day:"numeric", year:"numeric", hour:"numeric", minute:"2-digit", timeZoneName:"short"}).format(new Date(updated)) : "not yet updated";
  $("#last-updated").textContent = `Data loaded · ${state.records.length.toLocaleString()} archive records · Updated ${updateLabel}`;
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
  select.querySelectorAll("option[data-dynamic]").forEach(option => option.remove());
  [...new Set(values.filter(Boolean))].sort((a,b) => a.localeCompare(b)).forEach(value => { const option = new Option(value, value); option.dataset.dynamic = "true"; select.add(option); });
}
function populateSelects() {
  const active = viewRecords();
  addOptions("#category-filter", active.map(r => r.classification?.primary));
  addOptions("#agency-filter", active.map(r => r.award?.agency));
  addOptions("#company-filter", active.map(r => r.company?.canonical_name));
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
  state.filtered = viewRecords().filter(record => {
    const valueDate = record.announcement_date || record.action_date;
    const date = valueDate ? new Date(`${valueDate}T12:00:00Z`) : null;
    const datePass = dateMode === "custom" ? (!from || (date && date >= from)) && (!to || (date && date <= to)) : !cutoff || (date && date >= cutoff);
    const hqStatus = record.company?.hq_status;
    const hqPass = state.activeView === "work" || hq === "all" || (hq === "local" ? qualifiedStatuses.has(hqStatus) : hq === "review" ? [...qualifiedStatuses, "needs_review"].includes(hqStatus) : ["verified","strong"].includes(hqStatus));
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
  const summary = MarketView.summarize(state.filtered, [...techCategories]);
  $("#metric-awards").textContent = summary.awards.toLocaleString();
  $("#metric-value").textContent = formatValue(summary.value);
  $("#metric-companies").textContent = summary.companies.toLocaleString();
  $("#metric-tech").textContent = summary.techShare === null ? "—" : `${summary.techShare}%`;
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
    cell("company").innerHTML = `<span class="company-name">${escapeHtml(record.company?.canonical_name)}</span>${state.activeView === "moco" ? `<span class="hq-mini">MoCo entity: ${escapeHtml(record.company?.moco_city || record.company?.hq_city || "Under review")} · ${escapeHtml(mocoStatusLabel(record.company?.hq_status))}</span>` : `<span class="hq-mini">Outside Montgomery County · work location qualified</span>`}`;
    cell("company-location").textContent = safe(record.location?.recipient_location);
    cell("company-location").hidden = state.activeView !== "work";
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
function contactCard(label, contact) {
  if (!contact) return "";
  const copyButton = (value, name) => value ? `<button class="copy-control" type="button" data-copy="${escapeHtml(value)}" aria-label="Copy ${escapeHtml(name)}">Copy</button>` : "";
  const source = contact.source_url ? `<a href="${escapeHtml(contact.source_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(contact.source_name || "Public source")} ↗</a>` : "Source unavailable";
  return `<article class="contact-card"><h4>${escapeHtml(label)}</h4>
    <p class="contact-name"><strong>${escapeHtml(safe(contact.name, "Public contact"))}</strong>${contact.title || contact.office ? `<span>${escapeHtml(contact.title || contact.office)}</span>` : ""}</p>
    ${contact.email ? `<p><span>Email</span><a href="mailto:${escapeHtml(contact.email)}">${escapeHtml(contact.email)}</a>${copyButton(contact.email, "email address")}</p>` : contact.name ? `<p><span>Email</span>Not publicly available</p>` : ""}
    ${contact.phone ? `<p><span>Phone</span><a href="tel:${escapeHtml(contact.phone)}">${escapeHtml(contact.phone)}</a>${copyButton(contact.phone, "phone number")}</p>` : ""}
    <p class="contact-source"><span>${escapeHtml(safe(contact.contact_quality, "public"))} quality · verified source</span>${source}${contact.verified_date ? ` · ${escapeHtml(formatDate(contact.verified_date))}` : ""}</p>
  </article>`;
}
function openDetail(r) {
  const sources = (r.sources?.length ? r.sources : [r.source]).filter(s => s?.source_url);
  const hq = [r.company?.hq_city, r.company?.hq_state].filter(Boolean).join(", ") || "Under review";
  const outsideWork = r.market_relationship === "outside_company_working_in_moco";
  const reportedLocation = outsideWork ? safe(r.location?.recipient_location) : hq;
  const basisLine = outsideWork ? `<p>Market relationship: Outside company working in Montgomery County</p>` : `<p>MoCo basis: ${escapeHtml(mocoBasisLabel(r.company?.moco_basis))} (${Math.round(Number(r.company?.moco_confidence || 0) * 100)}% confidence)</p>`;
  const companyContact = r.contacts?.company;
  const federalContact = r.contacts?.federal || r.contacts?.government;
  const contactPanel = companyContact || federalContact ? `<section class="contacts-panel"><h3>Contacts</h3><p>Company and federal/award contacts are kept separate and shown only with public-source provenance.</p><div class="contact-grid">${contactCard("COMPANY CONTACT", companyContact)}${contactCard("FEDERAL / AWARD CONTACT", federalContact)}</div></section>` : "";
  const why = outsideWork ? `<section class="why-here"><h3>WHY THIS IS HERE</h3><p>This recipient is outside Montgomery County, but the official federal award lists a place of performance in Montgomery County, Maryland.</p></section>` : "";
  $("#detail-content").innerHTML = `<div class="detail-body">
    <div class="detail-title-row"><div><p class="section-kicker">${escapeHtml(r.classification?.primary)}</p><h2 id="detail-title">${escapeHtml(r.company?.canonical_name)}</h2><p>Reported entity location: ${escapeHtml(reportedLocation)} · <span class="confidence">${escapeHtml(mocoStatusLabel(r.company?.hq_status))}</span></p>${basisLine}</div><div class="detail-amount">${formatValue(r.award?.amount)}</div></div>
    <dl class="detail-grid">
      ${detailField("Ultimate parent", r.company?.ultimate_parent)}${detailField("Agency", r.award?.agency)}${detailField("Subagency", r.award?.subagency)}
      ${detailField("Contract number", r.award?.contract_number)}${detailField("Award ID", r.award?.award_id)}${detailField("Award type", r.award?.award_type)}
      ${detailField("Announcement date", formatDate(r.announcement_date))}${detailField("Action date", formatDate(r.action_date))}${detailField("Expected completion", r.award?.expected_completion)}
      ${detailField("NAICS", r.award?.naics)}${detailField("PSC", r.award?.psc)}${outsideWork ? detailField("Company location", r.location?.recipient_location) : ""}${detailField("Place of performance", r.location?.place_of_performance || r.location?.work_locations?.join("; "))}
    </dl>
    ${why}
    <div class="detail-description"><h3>What it was for</h3><p>${escapeHtml(r.award?.description)}</p></div>
    ${contactPanel}
    <div class="source-list"><h3>Sources and retrieval provenance</h3><p>The official record remains primary; retrieval-provider links document fallback provenance.</p><div class="source-list-links">${sources.map(source => sourceLink(source)).join("")}</div></div>
  </div>`;
  $("#detail-dialog").showModal();
}

function exportFilteredCsv() {
  const exportObjects = MarketView.exportRows(state.filtered);
  const headers = Object.keys(exportObjects[0] || {Date:"",Company:"","Company Location":"",Amount:"",Agency:"",Category:"","What It Was For":"","MoCo Work Location":"","Contract #":"",Source:"","Market Relationship":""});
  const rows = exportObjects.map(row => headers.map(header => row[header]));
  const csv = [headers, ...rows].map(row => row.map(value => `"${safe(value,"").replaceAll('"','""')}"`).join(",")).join("\r\n");
  const filename = state.activeView === "work" ? "work-in-montgomery-county-filtered.csv" : "montgomery-county-companies-filtered.csv";
  const link = Object.assign(document.createElement("a"), {href: URL.createObjectURL(new Blob([csv], {type:"text/csv;charset=utf-8"})), download:filename});
  link.click(); URL.revokeObjectURL(link.href);
}
function setActiveView(view) {
  state.activeView = view;
  document.querySelectorAll(".market-tab").forEach(button => {
    const active = button.dataset.view === view;
    button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active));
  });
  const work = view === "work";
  $("#view-subtitle").textContent = work ? "Federal contract awards to outside companies for work performed in Montgomery County, Maryland" : "Federal awards to companies and contracting entities based in Montgomery County, Maryland";
  $("#hq-filter-label").hidden = work;
  document.querySelectorAll(".company-location-column").forEach(cell => { cell.hidden = !work; });
  $("#work-location-heading").textContent = work ? "MoCo Work Location" : "Work location";
  $("#register-kicker").textContent = work ? "Montgomery County work register" : "Award register";
  $("#metric-awards-label").textContent = work ? "Awards performed in MoCo" : "Awards";
  $("#metric-value-label").textContent = work ? "Federal award value" : "Announced value";
  $("#metric-companies-label").textContent = work ? "Outside companies" : "Companies";
  $("#metric-companies-note").textContent = work ? "recipients based outside the county" : "Montgomery County entities";
  clearFilters(); populateSelects(); applyFilters();
}
function clearFilters() {
  $("#search").value = ""; $("#date-filter").value = "30"; $("#category-filter").value = ""; $("#agency-filter").value = ""; $("#company-filter").value = ""; $("#amount-filter").value = "0"; $("#hq-filter").value = "local"; $("#sort-filter").value = "newest"; $("#custom-dates").hidden = true; applyFilters();
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".market-tab").forEach(button => button.addEventListener("click", () => setActiveView(button.dataset.view)));
  ["#search","#date-from","#date-to"].forEach(id => $(id).addEventListener("input", applyFilters));
  ["#date-filter","#category-filter","#agency-filter","#company-filter","#amount-filter","#hq-filter","#sort-filter"].forEach(id => $(id).addEventListener("change", () => { if (id === "#date-filter") $("#custom-dates").hidden = $(id).value !== "custom"; applyFilters(); }));
  $("#clear-filters").addEventListener("click", clearFilters); $("#download-filtered").addEventListener("click", exportFilteredCsv);
  $("#retry-load").addEventListener("click", loadData);
  $("#dialog-close").addEventListener("click", () => $("#detail-dialog").close());
  $("#detail-content").addEventListener("click", async event => {
    const button = event.target.closest("[data-copy]"); if (!button) return;
    try { await navigator.clipboard.writeText(button.dataset.copy); button.textContent = "Copied"; setTimeout(() => { button.textContent = "Copy"; }, 1400); }
    catch (error) { button.textContent = "Copy failed"; console.error(error); }
  });
  $("#detail-dialog").addEventListener("click", event => { if (event.target === $("#detail-dialog")) $("#detail-dialog").close(); });
  document.addEventListener("keydown", event => { if (event.key === "/" && !/input|textarea|select/i.test(document.activeElement.tagName)) { event.preventDefault(); $("#search").focus(); } });
  loadData();
});
