import { t, tagLabel } from '../i18n.js'
import { catalogText } from '../data/catalog.js'
import { navigate } from '../router.js'
import { escapeHtml } from '../lib/html.js'

export function DomainCard(domain) {
  const el = document.createElement('article')
  el.className = 'cb-card'

  const tags = (domain.tags || [])
    .map(tag => `<span class="cb-tag" data-tag="${escapeHtml(tag)}">${escapeHtml(tagLabel(tag))}</span>`)
    .join('')

  // Catalog text is data (and editable on the Manage → i18n tab), so it's
  // escaped before going into this innerHTML template.
  el.innerHTML = `
    <div class="cb-card__header">
      <h2 class="cb-card__title">${escapeHtml(catalogText(domain, 'name'))}</h2>
      <div class="cb-card__tags">${tags}</div>
    </div>
    <p class="cb-card__stats">${t('card.stats', { nodes: domain.nodes, edges: domain.edges, primitives: domain.primitives })}</p>
    <p class="cb-card__desc">${escapeHtml(catalogText(domain, 'description'))}</p>
    <div class="cb-card__actions">
      <button class="cb-btn cb-btn--primary js-explore" ${!domain.has_navigator ? 'disabled' : ''}>
        ${t('card.explore')}
      </button>
      <span class="cb-book-indicator" title="${domain.has_book ? t('card.book_available') : ''}">${domain.has_book ? '📖' : ''}</span>
    </div>
  `

  el.querySelector('.js-explore').addEventListener('click', () => {
    navigate(`/domain/${domain.id}`)
  })

  return el
}
