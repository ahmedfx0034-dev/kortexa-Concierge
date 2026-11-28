// Ghana phone number helpers. WhatsApp's API wants digits only, with the
// country code and no "+" (e.g. "233241234567").

const MOBILE_PREFIXES = new Set(["20", "23", "24", "25", "26", "27", "28", "50", "53", "54", "55", "56", "57", "59"]);

/** Turn "+233 24 123 4567", "0241234567" or "233241234567" into "233241234567". Returns "" if invalid. */
export function normalizeGhana(input) {
  let d = String(input || "").replace(/\D/g, "");
  if (d.startsWith("00")) d = d.slice(2);
  if (d.startsWith("2330")) d = "233" + d.slice(4); // "+233 024..." typo
  if (d.length === 10 && d.startsWith("0")) d = "233" + d.slice(1);
  if (d.length === 9) d = "233" + d;
  if (/^233\d{9}$/.test(d)) return d;
  // Allow other international numbers (e.g. Nigeria +234) as-is.
  if (/^\d{10,15}$/.test(d) && !d.startsWith("0")) return d;
  return "";
}

/** True for Ghana mobile numbers (the ones that can be on WhatsApp). */
export function isGhanaMobile(waId) {
  return /^233\d{9}$/.test(waId) && MOBILE_PREFIXES.has(waId.slice(3, 5));
}

export function pretty(waId) {
  const m = /^233(\d{2})(\d{3})(\d{4})$/.exec(waId || "");
  return m ? `+233 ${m[1]} ${m[2]} ${m[3]}` : waId ? "+" + waId : "";
}
