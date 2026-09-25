import { Header } from '../components/Header.js'
import { t } from '../i18n.js'

export function About(container) {
  container.innerHTML = ''
  container.appendChild(Header())

  const main = document.createElement('main')
  main.className = 'cb-about'
  // The body is HTML kept per language in locales/ui.yaml (about.body).
  main.innerHTML = t('about.body')
  container.appendChild(main)
}
