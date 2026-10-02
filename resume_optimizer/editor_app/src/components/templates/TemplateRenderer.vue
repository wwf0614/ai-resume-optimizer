<template>
  <div class="resume-preview tpl-" :style="cssVars">
    <div v-if="meta.cover" class="tpl-cover">
      <h1>{{ data.basicInfo.name || '个人简历' }}</h1>
      <p>{{ data.jobIntention.position || '求职意向' }}</p>
    </div>
    <template v-for="key in order" :key="key">
      <section class="tpl-section" @click="emitOpen(key, 0)">
        <component :is="blockFor(key)" :data="data" :meta="meta" />
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, defineComponent, h } from 'vue'
import BasicBlock from './blocks/BasicBlock.vue'
import ListBlock from './blocks/ListBlock.vue'
import TextBlock from './blocks/TextBlock.vue'
import TagsBlock from './blocks/TagsBlock.vue'

const props = defineProps({
  data: { type: Object, required: true },
  meta: { type: Object, required: true },
  order: { type: Array, default: () => [] }
})
const emit = defineEmits(['open-edit'])

const cssVars = computed(() => ({
  '--theme-color': props.meta.themeColor,
  '--line-height': props.meta.lineHeight,
  '--module-gap': props.meta.moduleGap + 'px',
  '--page-margin': props.meta.pageMargin + 'px',
  '--font-size': props.meta.fontSize + 'px',
  '--font-family': props.meta.fontFamily
}))

const SECTION_META = {
  basic: { label: '基本信息' },
  job: { label: '意向职位' },
  education: { label: '教育背景', listKey: 'educationExp' },
  work: { label: '工作经验', listKey: 'workExp' },
  project: { label: '项目经历', listKey: 'projectExp' },
  internship: { label: '实习经历', listKey: 'internshipExp' },
  campus: { label: '校园经历', listKey: 'campusExp' },
  skills: { label: '特长技能' },
  honors: { label: '荣誉证书' },
  selfEval: { label: '自我评价' },
  hobbies: { label: '兴趣爱好' },
  custom: { label: '自定义' }
}

function emitOpen(key, index) {
  emit('open-edit', { sectionKey: key, index })
}

function blockFor(key) {
  const meta = SECTION_META[key] || { label: key }
  if (key === 'basic') {
    return defineComponent({
      setup: () => () => h(BasicBlock, { data: props.data, meta: props.meta, label: meta.label })
    })
  }
  if (key === 'job' || key === 'selfEval' || key === 'custom') {
    return defineComponent({
      setup: () => () => h(TextBlock, { data: props.data, meta: props.meta, sectionKey: key, label: meta.label })
    })
  }
  if (key === 'skills' || key === 'honors' || key === 'hobbies') {
    return defineComponent({
      setup: () => () => h(TagsBlock, { data: props.data, meta: props.meta, sectionKey: key, label: meta.label })
    })
  }
  return defineComponent({
    setup: () => () => h(ListBlock, { data: props.data, meta: props.meta, sectionKey: key, listKey: meta.listKey, label: meta.label })
  })
}
</script>
