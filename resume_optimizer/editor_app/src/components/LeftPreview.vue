<template>
  <RealTemplatePreview v-if="real.active" />
  <TemplateRenderer v-else :data="store.filteredData" :meta="store.meta"
                    :order="store.visibleModules"
                    @open-edit="$emit('open-edit', $event)" />
</template>

<script setup>
import { onMounted } from 'vue'
import { useResumeStore } from '../store/resumeStore'
import { useRealTemplateStore } from '../store/realTemplateStore'
import TemplateRenderer from './templates/TemplateRenderer.vue'
import RealTemplatePreview from './RealTemplatePreview.vue'

defineEmits(['open-edit'])
const store = useResumeStore()
const real = useRealTemplateStore()

onMounted(async () => {
  const list = await real.loadVipTemplates()
  if (real.templateId && list.some(t => t.id === real.templateId)) {
    if (!real.structure) await real.loadStructure(real.templateId)
  } else if (list.length) {
    await real.loadStructure(list[0].id)
  }
})
</script>
