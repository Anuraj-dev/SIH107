/** Client-side PII redact — keep in sync with bis_assistant.i18n_privacy.redact. */
const PII = [
  /(?:\+?91[\s-]?)?[6-9](?:[\s-]?\d){9}/g,
  /[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+/g,
  /\b\d{4}\s?\d{4}\s?\d{4}\b/g,
];

export function redactPii(text) {
  let out = String(text ?? "");
  for (const p of PII) {
    p.lastIndex = 0;
    out = out.replace(p, "[REDACTED]");
  }
  return out;
}

export function isHttpUrl(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url.trim());
}
