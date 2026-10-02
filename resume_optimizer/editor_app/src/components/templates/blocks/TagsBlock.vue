<template>
  <div class="tpl-block">
    <div class="tpl-head"><span>{{ label }}</span></div>
    <div v-if="!tags.length && !desc" class="tpl-empty-hint">点击编辑添加{{ label }}…</div>
    <template v-else>
      <div v-if="tags.length" class="tag-cloud">
        <span v-for="(t, i) in tags" :key="i" class="tag">{{ t }}</span>
      </div>
      <div v-if="desc" class="text-content" v-html="desc"></div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ data: Object, sectionKey: String, label: String })

const tags = computed(() => (props.data[props.sectionKey] || {}).tags || [])
const desc = computed(() => (props.data[props.sectionKey] || {}).description || '')
</script>

<style scoped>
.tag-cloud { display: flex; flex-wrap: wrap; gap: 8px; }
.tag { background: var(--theme-color); color: #fff; padding: 3px 13px; border-radius: 13px; font-size: 12.5px; }
.text-content { margin-top: 8px; font-size: 13px; color: #444; line-height: 1.8; }
</style>
