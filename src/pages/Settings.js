import { Header } from '../components/Header.js'
import { i18n, bindI18n, t } from '../i18n.js'

// Adapters that need a user-supplied API key (shown in the Settings form).
// claude_cli authenticates via the local CLI's own login; ollama is local —
// neither needs a key here. Keyed to match api/config.py's Settings field
// names (settings.js sends `${key}_api_key` in the PUT body).
const API_KEY_ADAPTERS = new Set(['anthropic', 'openai', 'google', 'openrouter'])

const ADAPTERS = {
  claude_cli: {
    label: 'Claude CLI',
    models: [
      { value: 'claude-sonnet-5', label: 'Sonnet 5' },
      { value: 'claude-haiku-4-5-20251001', label: 'Haiku 4.5' },
      { value: 'claude-opus-4-8', label: 'Opus 4.8' },
    ],
  },
  anthropic: {
    label: 'Anthropic',
    models: [
      { value: 'claude-sonnet-5', label: 'Claude Sonnet 5' },
      { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5' },
      { value: 'claude-opus-4-8', label: 'Claude Opus 4.8' },
    ],
  },
  openai: {
    label: 'OpenAI',
    models: [
      { value: 'gpt-4.1', label: 'GPT-4.1' },
      { value: 'gpt-5.4-mini', label: 'GPT 5.4 Mini' },
      { value: 'o3-mini', label: 'o3-mini' },
    ],
  },
  google: {
    label: 'Gemini',
    models: [
      { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
      { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
      { value: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash' },
    ],
  },
  openrouter: {
    label: 'OpenRouter',
    models: [
      { value: 'anthropic/claude-sonnet-5', label: 'Claude Sonnet 5' },
      { value: 'anthropic/claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5' },
      { value: 'anthropic/claude-opus-4-8', label: 'Claude Opus 4.8' },
      { value: 'google/gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
      { value: 'google/gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
      { value: 'google/gemini-3.5-flash', label: 'Gemini 3.5 Flash' },
      { value: 'openai/gpt-4.1', label: 'GPT-4.1' },
      { value: 'openai/gpt-5.4-mini', label: 'GPT 5.4 Mini' },
      { value: 'openai/o3-mini', label: 'o3-mini' },
      { value: 'deepseek/deepseek-r1', label: 'DeepSeek R1' },
      { value: 'meta-llama/llama-4-maverick', label: 'Llama 4 Maverick' },
      { value: 'z-ai/glm-5.2', label: 'GLM 5.2' },
      { value: 'qwen/qwen3.5-35b-a3b', label: 'Qwen 3.5 35B' },
      { value: 'qwen/qwen3.6-35b-a3b', label: 'Qwen 3.6 35B' },
      { value: 'nvidia/nemotron-3-ultra-550b-a55b:free', label: 'Nemotron 3 Ultra 550B' },
      { value: 'moonshotai/kimi-k2.6', label: 'Kimi 2.6' },
    ],
  },
  ollama: {
    label: 'Ollama (local)',
    models: null,
  },
}

async function populateModels(adapterSel, modelSel) {
  const adapter = ADAPTERS[adapterSel.value]
  modelSel.innerHTML = ''
  if (!adapter) return

  let models = adapter.models
  if (adapterSel.value === 'ollama' && !models) {
    try {
      const res = await fetch('/api/settings/ollama-models')
      if (res.ok) models = await res.json()
    } catch (_) {}
    if (!models || models.length === 0) {
      const opt = document.createElement('option')
      opt.value = ''
      i18n(opt, 'settings.ollama_unavailable')
      modelSel.appendChild(opt)
      return
    }
    ADAPTERS.ollama.models = models
  }

  for (const m of models) {
    const opt = document.createElement('option')
    opt.value = m.value
    opt.textContent = m.label
    modelSel.appendChild(opt)
  }
}

export async function Settings(container) {
  container.innerHTML = ''
  container.appendChild(Header())

  const main = document.createElement('main')
  main.className = 'cb-settings'
  main.innerHTML = `
    <h2 data-t="settings.title"></h2>
    <section class="cb-settings__section">
      <div class="cb-settings__section-title" data-t="settings.llm_section"></div>
      <div class="cb-settings__pair">
        <div class="cb-settings__field">
          <label class="cb-settings__label" data-t="settings.adapter"></label>
          <select id="cb-adapter" class="cb-settings__select">
            ${Object.entries(ADAPTERS).map(([k, v]) =>
              `<option value="${k}">${v.label}</option>`
            ).join('')}
          </select>
        </div>
        <div class="cb-settings__field cb-settings__field--grow">
          <label class="cb-settings__label" data-t="settings.model"></label>
          <select id="cb-model" class="cb-settings__select"></select>
        </div>
      </div>
      <div class="cb-settings__pair" id="cb-api-key-row" style="margin-top:12px">
        <div class="cb-settings__field cb-settings__field--grow">
          <label class="cb-settings__label" data-t="settings.api_key"></label>
          <input id="cb-api-key" type="password" class="cb-settings__select"
            data-t-placeholder="settings.api_key_placeholder" autocomplete="off" style="width:100%">
          <span id="cb-api-key-hint" style="font-size:0.78rem;color:#6b7280"></span>
        </div>
      </div>
      <div class="cb-settings__row" style="margin-top:16px">
        <button id="cb-settings-save" class="cb-btn" data-t="settings.save"></button>
        <span id="cb-settings-status" class="cb-settings__status"></span>
      </div>
      <div class="cb-settings__current" id="cb-current-llm"></div>
    </section>
    <section class="cb-settings__section">
      <div class="cb-settings__section-title" data-t="settings.limits_section"></div>
      <div class="cb-settings__pair">
        <div class="cb-settings__field">
          <label class="cb-settings__label" data-t="settings.while_max_iter"></label>
          <input id="cb-while-max-iter" type="number" min="1" step="1" value="50"
            class="cb-settings__select" style="width:100px"
            data-t-title="settings.while_max_iter_title">
        </div>
        <div class="cb-settings__field">
          <label class="cb-settings__label" data-t="settings.max_llm_calls"></label>
          <input id="cb-max-llm-calls" type="number" min="1" step="1" value="50"
            class="cb-settings__select" style="width:100px"
            data-t-title="settings.max_llm_calls_title">
        </div>
      </div>
      <div class="cb-settings__row" style="margin-top:16px">
        <button id="cb-spl-limits-save" class="cb-btn" data-t="settings.save"></button>
        <span id="cb-spl-limits-status" class="cb-settings__status"></span>
      </div>
    </section>
  `
  bindI18n(main)
  container.appendChild(main)

  // ── LLM section ────────────────────────────────────────────────────────────
  const adapterSel = main.querySelector('#cb-adapter')
  const modelSel = main.querySelector('#cb-model')
  const saveBtn = main.querySelector('#cb-settings-save')
  const status = main.querySelector('#cb-settings-status')
  const currentLlm = main.querySelector('#cb-current-llm')
  const apiKeyRow = main.querySelector('#cb-api-key-row')
  const apiKeyInput = main.querySelector('#cb-api-key')
  const apiKeyHint = main.querySelector('#cb-api-key-hint')

  // Whether each adapter's key is already saved server-side (booleans only
  // — the actual key value is never sent back). Populated once settings load.
  let keysSet = {}

  function updateApiKeyVisibility() {
    const adapter = adapterSel.value
    const needsKey = API_KEY_ADAPTERS.has(adapter)
    apiKeyRow.style.display = needsKey ? '' : 'none'
    apiKeyInput.value = ''
    i18n(apiKeyHint, () => (needsKey && keysSet[adapter] ? t('settings.key_saved') : ''))
  }

  adapterSel.addEventListener('change', () => {
    populateModels(adapterSel, modelSel)
    updateApiKeyVisibility()
  })
  await populateModels(adapterSel, modelSel)
  updateApiKeyVisibility()

  // ── SPL Limits section ─────────────────────────────────────────────────────
  const whileMaxIterInput = main.querySelector('#cb-while-max-iter')
  const maxLlmCallsInput = main.querySelector('#cb-max-llm-calls')
  const splLimitsSaveBtn = main.querySelector('#cb-spl-limits-save')
  const splLimitsStatus = main.querySelector('#cb-spl-limits-status')

  // ── Load current settings ──────────────────────────────────────────────────
  try {
    const res = await fetch('/api/settings')
    if (res.ok) {
      const data = await res.json()

      // LLM
      i18n(currentLlm, 'settings.current', { vars: { llm: data.llm } })
      const [adapter, ...modelParts] = data.llm.split(':')
      const model = modelParts.join(':')
      if (ADAPTERS[adapter]) {
        adapterSel.value = adapter
        await populateModels(adapterSel, modelSel)
        if ([...modelSel.options].some(o => o.value === model)) {
          modelSel.value = model
        }
      }

      // API key "already set" flags
      keysSet = {
        anthropic: data.anthropic_api_key_set,
        google: data.gemini_api_key_set,
        openai: data.openai_api_key_set,
        openrouter: data.openrouter_api_key_set,
      }
      updateApiKeyVisibility()

      // SPL limits
      if (data.spl_while_max_iter) whileMaxIterInput.value = data.spl_while_max_iter
      if (data.spl_max_llm_calls) maxLlmCallsInput.value = data.spl_max_llm_calls
    }
  } catch (_) {
    i18n(status, 'settings.api_unreachable_hint')
    status.style.color = '#dc2626'
  }

  // ── Save LLM ───────────────────────────────────────────────────────────────
  saveBtn.addEventListener('click', async () => {
    const adapter = adapterSel.value
    const llm = `${adapter}:${modelSel.value}`
    const body = { llm }
    // Only send a key field when the user actually typed something —
    // omitting it leaves the previously-saved key untouched.
    if (API_KEY_ADAPTERS.has(adapter) && apiKeyInput.value.trim()) {
      const field = adapter === 'google' ? 'gemini_api_key' : `${adapter}_api_key`
      body[field] = apiKeyInput.value.trim()
    }
    try {
      const res = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (res.ok) {
        const data = await res.json()
        keysSet = {
          anthropic: data.anthropic_api_key_set,
          google: data.gemini_api_key_set,
          openai: data.openai_api_key_set,
          openrouter: data.openrouter_api_key_set,
        }
        updateApiKeyVisibility()
        i18n(currentLlm, 'settings.current', { vars: { llm } })
        status.textContent = t('settings.saved')
        status.style.color = '#16a34a'
      } else {
        status.textContent = t('settings.save_failed')
        status.style.color = '#dc2626'
      }
    } catch (_) {
      status.textContent = t('settings.api_unreachable')
      status.style.color = '#dc2626'
    }
    setTimeout(() => { status.textContent = '' }, 3000)
  })

  // ── Save SPL Limits ────────────────────────────────────────────────────────
  splLimitsSaveBtn.addEventListener('click', async () => {
    const whileMaxIter = Number(whileMaxIterInput.value)
    const maxLlmCalls = Number(maxLlmCallsInput.value)
    if (!Number.isInteger(whileMaxIter) || whileMaxIter < 1 || !Number.isInteger(maxLlmCalls) || maxLlmCalls < 1) {
      splLimitsStatus.textContent = t('settings.invalid_limits')
      splLimitsStatus.style.color = '#dc2626'
      setTimeout(() => { splLimitsStatus.textContent = '' }, 3000)
      return
    }
    try {
      const res = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ spl_while_max_iter: whileMaxIter, spl_max_llm_calls: maxLlmCalls }),
      })
      if (res.ok) {
        splLimitsStatus.textContent = t('settings.saved')
        splLimitsStatus.style.color = '#16a34a'
      } else {
        splLimitsStatus.textContent = t('settings.save_failed')
        splLimitsStatus.style.color = '#dc2626'
      }
    } catch (_) {
      splLimitsStatus.textContent = t('settings.api_unreachable')
      splLimitsStatus.style.color = '#dc2626'
    }
    setTimeout(() => { splLimitsStatus.textContent = '' }, 3000)
  })
}
