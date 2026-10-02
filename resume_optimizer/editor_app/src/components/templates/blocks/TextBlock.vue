<template>
  <div class="tpl-block">
    <div class="tpl-head"><span>{{ label }}</span></div>
    <div v-if="sectionKey === 'job'" class="job-line">
      <span v-for="f in jobFields" :key="f.key" class="job-item">
        <b>{{ f.label }}：</b>{{ f.value || '—' }}
      </span>
    </div>
    <div v-else-if="!text" class="tpl-empty-hint">点击编辑填写{{ label }}…</div>
    <div v-else class="text-content" v-html="text"></div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { stripHtml } from '../../../utils/resumeHelpers'

const props = defineProps({ data: Object, sectionKey: String, label: String })

const text = computed(() => {
  if (props.sectionKey === 'custom') return props.data.custom.description || ''
  if (props.sectionKey === 'selfEval') return props.data.selfEvaluation.description || ''
  return ''
})
const jobFields = computed(() => {
  const j = props.data.jobIntention || {}
  return [
    { key: 'position', label: '期望职位', value: j.position },
    { key: 'city', label: '期望城市', value: j.city },
    { key: 'salary', label: '期望薪资', value: j.salary },
    { key: 'entryTime', label: '到岗时间', value: j.entryTime }
  ].filter(f => f.value)
})
</script>

<style scoped>
.text-content { font-size: 13px; color: #444; line-height: 1.85; white-space: pre-wrap; }
.job-line { display: flex; flex-wrap: wrap; gap: 6px 26px; font-size: 13px; }
.job-item { color: #444; }
.job-item b { color: #222; font-weight: 600; }
</style>
