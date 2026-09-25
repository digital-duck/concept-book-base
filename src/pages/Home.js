import { loadCatalog } from '../data/catalog.js'
import { DomainCard } from '../components/DomainCard.js'
import { Header } from '../components/Header.js'
import { t, tagLabel } from '../i18n.js'

export async function Home(container) {
  container.innerHTML = ''
  container.appendChild(Header())

  const main = document.createElement('main')
  main.className = 'cb-home'
  main.innerHTML = `<p class="cb-loading">${t('loading')}</p>`
  container.appendChild(main)

  let catalog
  try {
    catalog = await loadCatalog()
  } catch (err) {
    main.innerHTML = `<p class="cb-error">${t('home.load_error', { error: err.message })}</p>`
    return
  }

  const allTags = [...new Set(catalog.flatMap(d => d.tags))].sort()
  const allLevels = ['intro', 'core', 'college', 'research']
  let activeTag = 'all'
  let activeLevel = 'all'

  function render() {
    let filtered = catalog
    if (activeTag !== 'all') filtered = filtered.filter(d => d.tags.includes(activeTag))
    if (activeLevel !== 'all') filtered = filtered.filter(d => d.default_level === activeLevel)

    main.innerHTML = `
      <div class="cb-home__filters">
        <span class="cb-filter-group">
          <span class="cb-filter-label">${t('home.filter.subject')}</span>
          <button class="cb-filter-btn ${activeTag === 'all' ? 'active' : ''}" data-tag="all">${t('home.filter.all')}</button>
          ${allTags.map(t_ =>
            `<button class="cb-filter-btn ${activeTag === t_ ? 'active' : ''}" data-tag="${t_}">${tagLabel(t_)}</button>`
          ).join('')}
        </span>
        <span class="cb-filter-right">
          <span class="cb-filter-label">${t('home.filter.level')}</span>
          <select class="cb-level-select" id="cb-level-filter">
            <option value="all" ${activeLevel === 'all' ? 'selected' : ''}>${t('home.filter.all')}</option>
            ${allLevels.map(l =>
              `<option value="${l}" ${activeLevel === l ? 'selected' : ''}>${t(`level.${l}`)}</option>`
            ).join('')}
          </select>
        </span>
      </div>
      <div class="cb-card-grid"></div>
    `

    const grid = main.querySelector('.cb-card-grid')
    filtered.forEach(domain => grid.appendChild(DomainCard(domain)))

    main.querySelectorAll('.cb-filter-btn[data-tag]').forEach(btn => {
      btn.addEventListener('click', () => { activeTag = btn.dataset.tag; render() })
    })
    main.querySelector('#cb-level-filter').addEventListener('change', e => {
      activeLevel = e.target.value; render()
    })
  }

  render()
}
