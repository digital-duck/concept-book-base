import './style.css'
import { register, start, refresh } from './router.js'
import { applyI18n } from './i18n.js'
import { Home } from './pages/Home.js'
import { Domain } from './pages/Domain.js'
import { About } from './pages/About.js'
import { Settings } from './pages/Settings.js'

const app = document.getElementById('app')

register('/', () => Home(app))
register('/about', () => About(app))
register('/settings', () => Settings(app))
register('/domain/:id', (params) => Domain(app, params))

// Language switch: the domain page (graph iframe, zoom, selection) and
// Settings (unsaved form input) relabel in place; other pages re-render.
const _IN_PLACE = /^#\/(domain\/|settings\b)/
window.addEventListener('cb:localeChanged', () => {
  if (_IN_PLACE.test(window.location.hash)) applyI18n(document)
  else refresh()
})

start()
