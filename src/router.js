const _routes = {}

export function register(pattern, handler) {
  _routes[pattern] = handler
}

export function navigate(path) {
  window.location.hash = path
}

function _resolve() {
  const hash = window.location.hash.slice(1) || '/'

  const domainMatch = hash.match(/^\/domain\/([^?]+)/)
  if (domainMatch) {
    _routes['/domain/:id']?.({ id: decodeURIComponent(domainMatch[1]) })
    return
  }

  // Generic: match on the path part, pass any ?query as params
  // (e.g. /settings?tab=x)
  const [path, qs] = hash.split('?')
  _routes[path]?.(Object.fromEntries(new URLSearchParams(qs || '')))
}

// Re-render the current route (e.g. after a locale change).
export function refresh() {
  _resolve()
}

export function start() {
  window.addEventListener('hashchange', _resolve)
  _resolve()
}
