// Minimal HTML-escape for interpolating arbitrary text (an error message,
// a server-returned `detail` string, free-form user/LLM-authored content)
// into a template-literal innerHTML string. Anything that can carry
// attacker- or LLM-influenced text into an innerHTML sink needs this —
// most concretely, api/services/path_safety.py's safe_segment() error
// messages echo the raw invalid value back in `detail` (e.g. `Invalid
// domain_id: '<img onerror=...>' ...`), so an error banner that renders
// `err.message`/`data.detail` unescaped is a real reflected-XSS path, not
// just a theoretical one (see tests/snyk/code-2.txt's "exception flows
// into innerHTML" findings).
export function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
