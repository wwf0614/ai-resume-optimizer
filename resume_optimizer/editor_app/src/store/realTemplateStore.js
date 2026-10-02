import { defineStore } from 'pinia'

const LS_KEY = 'resume_planet_real_tpl_v2'

function authHeader() {
  const t = localStorage.getItem('resume_planet_token') || sessionStorage.getItem('resume_planet_token')
  return t ? { Authorization: 'Bearer ' + t } : {}
}

export const useRealTemplateStore = defineStore('realTemplate', {
  state: () => {
    let saved = null
    try { saved = JSON.parse(localStorage.getItem(LS_KEY) || 'null') } catch (e) { saved = null }
    return {
      templateId: (saved && saved.templateId) || null,
      boxTexts: (saved && saved.boxTexts) || {},
      structure: null,
      vipTemplates: [],
      loading: false,
      error: ''
    }
  },
  getters: {
    active(state) {
      return !!state.structure && !!state.templateId
    }
  },
  actions: {
    persist() {
      try {
        localStorage.setItem(LS_KEY, JSON.stringify({ templateId: this.templateId, boxTexts: this.boxTexts }))
      } catch (e) { /* ignore */ }
    },
    async loadVipTemplates() {
      try {
        const r = await fetch('/api/vip-templates', { headers: authHeader() })
        if (!r.ok) throw new Error('HTTP ' + r.status)
        this.vipTemplates = await r.json()
      } catch (e) {
        this.vipTemplates = []
        this.error = e.message
      }
      return this.vipTemplates
    },
    async loadStructure(id) {
      this.loading = true
      this.error = ''
      try {
        const r = await fetch('/api/template-structure/' + id, { headers: authHeader() })
        if (!r.ok) throw new Error('HTTP ' + r.status)
        this.structure = await r.json()
        this.templateId = id
        if (!this.boxTexts || typeof this.boxTexts !== 'object') {
          const fresh = {}
          ;(this.structure.boxes || []).forEach(b => { fresh[b.id] = b.text || '' })
          this.boxTexts = fresh
        }
        this.persist()
      } catch (e) {
        this.error = e.message
      } finally {
        this.loading = false
      }
    },
    setBoxText(id, text) {
      this.boxTexts = Object.assign({}, this.boxTexts, { [id]: text })
      this.persist()
    },
    reset() {
      this.structure = null
      this.templateId = null
      this.boxTexts = {}
      try { localStorage.removeItem(LS_KEY) } catch (e) { /* ignore */ }
    }
  }
})
