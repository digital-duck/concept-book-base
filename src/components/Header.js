import { i18n } from '../i18n.js'
import { appConfig } from '../config.js'
import { LanguagePicker } from './LanguagePicker.js'

// domainName: a string, or a function returning the (localized) name — a
// function is re-evaluated in place on a locale change (see i18n()).
export function Header({ domainName = '' } = {}) {
  const el = document.createElement('header')
  el.className = 'cb-header'

  const topRow = document.createElement('div')
  topRow.className = 'cb-header__top'

  const logo = document.createElement('a')
  logo.className = 'cb-header__logo'
  logo.href = '#/'
  if (appConfig.logoImage) {
    const img = document.createElement('img')
    img.src = appConfig.logoImage
    i18n(img, 'app.title', { attr: 'alt' })
    logo.appendChild(img)
  } else {
    i18n(logo, 'app.title')
  }
  topRow.appendChild(logo)

  if (domainName) {
    const sep = document.createElement('span')
    sep.className = 'cb-header__sep'
    sep.textContent = '›'
    topRow.appendChild(sep)

    const dn = document.createElement('span')
    dn.className = 'cb-header__domain'
    if (typeof domainName === 'function') i18n(dn, domainName)
    else dn.textContent = domainName
    topRow.appendChild(dn)
  }

  const spacer = document.createElement('span')
  spacer.className = 'cb-header__spacer'
  topRow.appendChild(spacer)

  const nav = document.createElement('nav')
  nav.className = 'cb-header__nav'

  const settingsLink = document.createElement('a')
  settingsLink.href = '#/settings'
  i18n(settingsLink, 'nav.settings')
  nav.appendChild(settingsLink)

  nav.appendChild(LanguagePicker())

  const aboutLink = document.createElement('a')
  aboutLink.href = '#/about'
  i18n(aboutLink, 'nav.about')
  nav.appendChild(aboutLink)

  topRow.appendChild(nav)

  el.appendChild(topRow)

  return el
}
