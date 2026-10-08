(function (root) {
  "use strict";
  const MOCO_RELATIONSHIPS = new Set(["moco_company", "moco_company_working_in_moco"]);

  function recordsForView(records, view) {
    if (view === "work") return records.filter(record => record.market_relationship === "outside_company_working_in_moco");
    return records.filter(record => MOCO_RELATIONSHIPS.has(record.market_relationship));
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

  function exportRows(records) {
    return records.map(record => ({
      Date: record.announcement_date || record.action_date,
      Company: record.company?.canonical_name,
      "Company Location": record.location?.recipient_location,
      Amount: record.award?.amount,
      Agency: record.award?.agency,
      Category: record.classification?.primary,
      "What It Was For": record.award?.description,
      "MoCo Work Location": record.location?.place_of_performance,
      "Contract #": record.award?.contract_number || record.award?.award_id,
      Source: record.source?.source_url,
      "Market Relationship": record.market_relationship,
    }));
  }

  const api = {recordsForView, summarize, exportRows};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.MarketView = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
