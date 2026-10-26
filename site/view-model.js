(function (root) {
  "use strict";
  const MIN_VISIBLE_AMOUNT = 10_000;
  const MOCO_RELATIONSHIPS = new Set(["moco_company", "moco_company_working_in_moco"]);

  function hasVisibleAmount(record) {
    const amount = Number(record.award?.amount);
    return Number.isFinite(amount) && amount >= MIN_VISIBLE_AMOUNT;
  }

  function recordsForView(records, view) {
    const qualifying = records.filter(hasVisibleAmount);
    if (view === "work") return qualifying.filter(record => record.market_relationship === "outside_company_working_in_moco");
    return qualifying.filter(record => MOCO_RELATIONSHIPS.has(record.market_relationship));
  }

  function recordsForMonth(records, year, month) {
    const prefix = `${Number(year)}-${String(Number(month)).padStart(2, "0")}`;
    return records.filter(record => String(record.announcement_date || record.action_date || "").startsWith(prefix));
  }

  function summarize(records, techCategories) {
    const tech = new Set(techCategories || []);
    return {
      awards: records.length,
      value: records.reduce((sum, record) => sum + (Number(record.award?.amount) || 0), 0),
      companies: new Set(records.map(record => record.company?.canonical_name).filter(Boolean)).size,
      techShare: records.length ? Math.round(records.filter(record => tech.has(record.classification?.primary)).length / records.length * 100) : null,
    };
  }

  function exportRows(records, view = "moco") {
    return records.map(record => {
      const row = {
        Date: record.announcement_date || record.action_date || null,
        Company: record.company?.canonical_name ?? null,
      };
      if (view === "work") row["Company Location"] = record.location?.recipient_location ?? null;
      row.Amount = record.award?.amount ?? null;
      row.Agency = record.award?.subagency || record.award?.agency || null;
      row.Category = record.classification?.primary ?? null;
      row["What It Was For"] = record.award?.description ?? null;
      row[view === "work" ? "MoCo Work Location" : "Work Location"] = record.location?.place_of_performance || record.location?.work_locations?.join("; ") || null;
      row["Contract #"] = record.award?.contract_number || record.award?.award_id || null;
      row.Source = record.source?.source_url ?? null;
      return row;
    });
  }

  const api = {MIN_VISIBLE_AMOUNT, recordsForView, recordsForMonth, summarize, exportRows};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.MarketView = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
