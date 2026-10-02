import { defineStore } from 'pinia'
import { cleanResumeData, emptyItemFor, uuid } from '../utils/resumeHelpers'

const LS_KEY = 'resume_planet_editor_v2'

const DEFAULT_STATE = () => ({
  meta: {
    templateId: 'modern-blue',
    themeColor: '#5340f5',
    fontSize: 14,
    fontFamily: '微软雅黑',
    lineHeight: 1.35,
    moduleGap: 6,
    pageMargin: 33,
    cover: false
  },
  modulesOrder: [
    'basic', 'job', 'education', 'work', 'project', 'internship',
    'campus', 'skills', 'honors', 'selfEval', 'hobbies', 'custom'
  ],
  moduleVisibility: {
    basic: true, job: true, education: true, work: true, project: false,
    internship: false, campus: false, skills: true, honors: false,
    selfEval: true, hobbies: false, custom: false
  },
  basicInfo: {
    name: '', gender: '', birthday: '', showAge: true,
    phone: '', email: '', maritalStatus: '', workYears: '',
    height: '', weight: '', nation: '', birthPlace: '',
    politicalStatus: '', avatar: '', showAvatar: true,
    customFields: []
  },
  educationExp: [],
  workExp: [],
  projectExp: [],
  internshipExp: [],
  campusExp: [],
  skills: { tags: [], description: '' },
  honors: { items: [], description: '' },
  selfEvaluation: { description: '' },
  hobbies: { tags: [], description: '' },
  jobIntention: { position: '', city: '', salary: '', entryTime: '' },
  custom: { title: '自定义', description: '' }
})

export const useResumeStore = defineStore('resume', {
  state: () => {
    let saved = null
    try { saved = JSON.parse(localStorage.getItem(LS_KEY) || 'null') } catch (e) { saved = null }
    const base = DEFAULT_STATE()
    if (saved && saved.meta) {
      // 合并保存的数据
      return Object.assign(base, saved)
    }
    return base
  },
  getters: {
    filteredData(state) {
      return cleanResumeData(state)
    },
    visibleModules(state) {
      return state.modulesOrder.filter(k => state.moduleVisibility[k])
    }
  },
  actions: {
    updateMeta(payload) {
      this.meta = Object.assign({}, this.meta, payload)
      this.save()
    },
    toggleModule(name) {
      this.moduleVisibility[name] = !this.moduleVisibility[name]
      this.save()
    },
    updateModulesOrder(newOrder) {
      this.modulesOrder = newOrder
      this.save()
    },
    addModuleItem(sectionKey, preset) {
      const item = preset || emptyItemFor(sectionKey)
      item.id = item.id || uuid()
      this[sectionKey].push(item)
      this.save()
      return item
    },
    removeModuleItem(sectionKey, id) {
      this[sectionKey] = this[sectionKey].filter(it => it.id !== id)
      this.save()
    },
    moveModuleItem(sectionKey, index, dir) {
      const arr = this[sectionKey]
      const j = index + dir
      if (index < 0 || j < 0 || j >= arr.length) return
      const tmp = arr[index]
      arr[index] = arr[j]
      arr[j] = tmp
      this.save()
    },
    updateRichText(sectionKey, index, field, htmlContent) {
      const target = this[sectionKey][index]
      if (target) { target[field] = htmlContent }
      this.save()
    },
    updateBasic(payload) {
      this.basicInfo = Object.assign({}, this.basicInfo, payload)
      this.save()
    },
    addCustomField() {
      this.basicInfo.customFields.push({ label: '', value: '' })
      this.save()
    },
    removeCustomField(i) {
      this.basicInfo.customFields.splice(i, 1)
      this.save()
    },
    updateTags(sectionKey, tags) {
      this[sectionKey].tags = tags
      this.save()
    },
    updateTextSection(sectionKey, payload) {
      this[sectionKey] = Object.assign({}, this[sectionKey], payload)
      this.save()
    },
    save() {
      try {
        localStorage.setItem(LS_KEY, JSON.stringify(this.$state))
      } catch (e) { /* 忽略 */ }
    }
  }
})
