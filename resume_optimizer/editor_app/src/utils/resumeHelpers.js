// 数据清洗与工具函数
export function uuid() {
  return 'id-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8)
}

export function emptyItemFor(sectionKey) {
  const base = { id: null }
  if (sectionKey === 'educationExp') {
    return Object.assign(base, { school: '', major: '', degree: '', startDate: '', endDate: '', isCurrent: false, description: '' })
  }
  if (sectionKey === 'workExp' || sectionKey === 'internshipExp') {
    return Object.assign(base, { company: '', position: '', startDate: '', endDate: '', isCurrent: false, description: '' })
  }
  if (sectionKey === 'projectExp') {
    return Object.assign(base, { name: '', role: '', startDate: '', endDate: '', isCurrent: false, description: '' })
  }
  if (sectionKey === 'campusExp') {
    return Object.assign(base, { title: '', role: '', startDate: '', endDate: '', isCurrent: false, description: '' })
  }
  return Object.assign(base, { description: '' })
}

// 高阶清洗：过滤空行/空值，防止预览区大片空白
export function cleanResumeData(state) {
  const data = JSON.parse(JSON.stringify(state))

  data.basicInfo.customFields = (data.basicInfo.customFields || []).filter(f => (f.label || '').trim() && (f.value || '').trim())

  const listKeys = ['educationExp', 'workExp', 'projectExp', 'internshipExp', 'campusExp']
  listKeys.forEach(key => {
    data[key] = (data[key] || []).filter(item => {
      const joined = Object.values(item).filter(v => typeof v === 'string').join('')
      return joined.trim() !== ''
    })
  })

  data.skills.tags = (data.skills.tags || []).filter(t => (t || '').trim())
  data.honors.items = (data.honors.items || []).filter(t => (t || '').trim())
  data.hobbies.tags = (data.hobbies.tags || []).filter(t => (t || '').trim())
  return data
}

export function stripHtml(html) {
  const div = document.createElement('div')
  div.innerHTML = html || ''
  return div.textContent || ''
}
