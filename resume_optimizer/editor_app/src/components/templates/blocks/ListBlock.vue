<template>
  <div class="tpl-block">
    <div class="tpl-head"><span>{{ label }}</span></div>
    <div v-if="!items.length" class="tpl-empty-hint">点击编辑添加{{ label }}…</div>
    <div v-for="(it, i) in items" :key="it.id || i" class="list-item">
      <div class="list-head">
        <span class="list-title">{{ titleOf(it) }}</span>
        <span class="list-role">{{ roleOf(it) }}</span>
        <span class="list-time">{{ timeOf(it) }}</span>
      </div>
      <div class="list-desc" v-html="it.description || ''"></div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { stripHtml } from '../../../utils/resumeHelpers'

const props = defineProps({ data: Object, listKey: String, label: String })
const items = computed(() => props.data[props.listKey] || [])

function titleOf(it) {
  return it.company || it.school || it.name || it.title || ''
}
function roleOf(it) {
  return it.position || it.major || it.role || ''
}
function timeOf(it) {
  const s = it.startDate || ''
  const e = it.isCurrent ? '至今' : (it.endDate || '')
  return [s, e].filter(Boolean).join(' ~ ')
}
</script>

<style scoped>
.list-item { margin-bottom: 10px; }
.list-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.list-title { font-weight: 700; font-size: 14px; color: #222; }
.list-role { color: var(--theme-color); font-size: 12.5px; font-weight: 600; }
.list-time { margin-left: auto; color: #888; font-size: 12px; }
.list-desc { font-size: 13px; color: #555; line-height: 1.7; margin-top: 4px; }
</style>
