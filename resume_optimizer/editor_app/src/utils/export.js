import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'
import { stripHtml } from './resumeHelpers'

function findPreview() {
  return document.querySelector('.resume-preview')
}

async function capture() {
  const el = findPreview()
  if (!el) throw new Error('未找到简历预览')
  return html2canvas(el, { scale: 2, backgroundColor: '#ffffff', useCORS: true })
}

export async function exportResume(cmd, store) {
  try {
    if (cmd === 'print') {
      document.body.classList.add('printing')
      window.print()
      setTimeout(() => document.body.classList.remove('printing'), 500)
      return
    }
    const canvas = await capture()
    if (cmd === 'png') {
      const a = document.createElement('a')
      a.download = (store.basicInfo.name || '简历') + '.png'
      a.href = canvas.toDataURL('image/png')
      a.click()
      return
    }
    if (cmd === 'pdf') {
      const img = canvas.toDataURL('image/jpeg', 0.95)
      const pdf = new jsPDF({
        orientation: 'portrait',
        unit: 'px',
        format: [canvas.width / 2, canvas.height / 2],
        hotfixes: ['px_scaling']
      })
      pdf.addImage(img, 'JPEG', 0, 0, canvas.width / 2, canvas.height / 2)
      pdf.save((store.basicInfo.name || '简历') + '.pdf')
      return
    }
    throw new Error('未知导出格式')
  } catch (e) {
    console.error('导出失败:', e)
    alert('导出失败：' + e.message)
  }
}

// 真实模板（VIP docx）导出：写回文本框并下载
export async function exportRealTemplate(cmd, real) {
  const fmt = cmd === 'pdf' ? 'pdf' : 'docx'
  try {
    const t = localStorage.getItem('resume_planet_token') || sessionStorage.getItem('resume_planet_token')
    const fd = new FormData()
    fd.append('edits', JSON.stringify(real.boxTexts || {}))
    fd.append('format', fmt)
    const r = await fetch('/api/template-save/' + real.templateId, {
      method: 'POST',
      headers: t ? { Authorization: 'Bearer ' + t } : {},
      body: fd
    })
    if (!r.ok) {
      const txt = await r.text()
      let d = {}
      try { d = JSON.parse(txt) } catch (e) { /* ignore */ }
      throw new Error(d.detail || d.error || ('HTTP ' + r.status))
    }
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = (fmt === 'pdf' ? '简历.pdf' : '简历.docx')
    document.body.appendChild(a)
    a.click()
    setTimeout(() => { a.remove(); URL.revokeObjectURL(url) }, 120)
  } catch (e) {
    console.error('导出失败:', e)
    alert('导出失败：' + e.message)
  }
}

export { stripHtml }
