<template>
  <div class="rt-wrap">
    <div v-if="real.loading" class="rt-loading">正在加载模板结构…</div>
    <div v-else-if="real.error" class="rt-loading">模板加载失败：{{ real.error }}</div>
    <div v-else-if="real.structure" class="rt-page" :style="pageStyle">
      <div v-for="box in visibleBoxes" :key="real.templateId + '-' + box.id"
           ref="boxEls" class="rt-box" contenteditable="true"
           :data-ph="(box.placeholders || [])[0] || ''"
           :style="boxStyle(box)"
           @input="onInput($event, box.id)"
           @focus="onFocus($event)"
           @blur="onBlur($event)"></div>
    </div>
    <div v-else class="rt-loading">请在「更换模板」中选择 VIP 模板</div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useRealTemplateStore } from '../store/realTemplateStore'
import { useResumeStore } from '../store/resumeStore'

const real = useRealTemplateStore()
const resume = useResumeStore()
const boxEls = ref([])

const MODULE_MAP = [
  { module: 'basic', labels: ['姓名', '电话', '邮箱', '微信', '地址', '基本信息', '年龄', '学历', '性别', '籍贯', '民族', '身高', '体重'] },
  { module: 'education', labels: ['教育背景'] },
  { module: 'work', labels: ['工作经历', '工作经验'] },
  { module: 'internship', labels: ['实习经验', '实习经历'] },
  { module: 'project', labels: ['项目经验', '项目经历'] },
  { module: 'campus', labels: ['校园经历'] },
  { module: 'skills', labels: ['职业技能', '技能特长'] },
  { module: 'selfEval', labels: ['自我评价', '个人优势'] },
  { module: 'honors', labels: ['荣誉证书'] },
  { module: 'hobbies', labels: ['兴趣爱好'] }
]

const scale = computed(() => {
  const w = (real.structure && real.structure.page_w) || 794
  return Math.min(1, 720 / w)
})
const pageStyle = computed(() => ({
  width: Math.round(((real.structure && real.structure.page_w) || 794) * scale.value) + 'px',
  minHeight: Math.round(((real.structure && real.structure.page_h) || 1123) * scale.value) + 'px'
}))

function boxVisible(box) {
  if (box.editable === false) return false
  // 管理端配置优先：盒子归属某个模块时随模块开关显隐
  const cfg = (real.structure && real.structure.config) || {}
  const entry = cfg[box.id]
  if (entry && entry.module) {
    return resume.moduleVisibility[entry.module] !== false
  }
  const ph = box.placeholders || []
  if (!ph.length) return true
  const rule = MODULE_MAP.find(r => ph.some(l => r.labels.includes(l)))
  if (!rule) return true
  return resume.moduleVisibility[rule.module] !== false
}

const visibleBoxes = computed(() => ((real.structure && real.structure.boxes) || []).filter(boxVisible))

function boxStyle(box) {
  const s = scale.value
  const p0 = (box.paragraphs && box.paragraphs[0]) || null
  const r0 = (p0 && p0.runs && p0.runs[0]) || {}
  const style = {
    left: Math.round(box.x * s) + 'px',
    top: Math.round(box.y * s) + 'px',
    width: Math.round(box.w * s) + 'px',
    height: Math.round(box.h * s) + 'px',
    fontSize: Math.max(10, Math.round((r0.size || 12) * s)) + 'px'
  }
  if (r0.bold) style.fontWeight = '700'
  if (r0.italic) style.fontStyle = 'italic'
  if (r0.color) style.color = r0.color
  if (r0.font) style.fontFamily = r0.font
  return style
}

function displayText(box) {
  const raw = real.boxTexts[box.id] != null ? real.boxTexts[box.id] : (box.text || '')
  return String(raw).replace(/\{\{[^}]*\}\}/g, '')
}

function onInput(e, id) {
  real.setBoxText(id, e.target.innerText)
}
function onFocus(e) { e.target.classList.add('editing') }
function onBlur(e) { e.target.classList.remove('editing') }

watch(visibleBoxes, async () => {
  await nextTick()
  boxEls.value.forEach((el, i) => {
    const box = visibleBoxes.value[i]
    if (el && box) el.textContent = displayText(box)
  })
}, { immediate: true })
</script>

<style scoped>
.rt-wrap { display: flex; justify-content: center; width: 100%; }
.rt-loading { color: #999; font-size: 14px; padding: 60px 0; }
.rt-page {
  position: relative; background: #fff; box-shadow: 0 2px 16px rgba(0, 0, 0, .08);
  flex-shrink: 0;
}
.rt-box {
  position: absolute; outline: none; cursor: text;
  white-space: pre-wrap; word-break: break-word; line-height: 1.45;
  border: 1px dashed transparent; border-radius: 2px;
  transition: border-color .15s, box-shadow .15s;
}
.rt-box:hover { border-color: #c7bfff; }
.rt-box.editing { border-color: #5340f5; box-shadow: 0 0 0 2px rgba(83, 64, 245, .12); }
.rt-box:empty::before { content: attr(data-ph); color: #b9c0d0; }
</style>
