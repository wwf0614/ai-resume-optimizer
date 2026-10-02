<template>
  <div class="ed-app">
    <TopToolbar />
    <div class="ed-main">
      <div class="ed-left">
        <LeftPreview @open-edit="openEdit" />
      </div>
      <RightPanel @open-edit="openEdit" />
    </div>
    <EditBasicModal v-model="showBasic" />
    <EditListModal
      v-model="showList"
      :section-key="listSection"
      :index="listIndex"
    />
    <VipGate />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import TopToolbar from './components/TopToolbar.vue'
import LeftPreview from './components/LeftPreview.vue'
import RightPanel from './components/RightPanel.vue'
import EditBasicModal from './components/modals/EditBasicModal.vue'
import EditListModal from './components/modals/EditListModal.vue'
import VipGate from './components/VipGate.vue'

const showBasic = ref(false)
const showList = ref(false)
const listSection = ref('workExp')
const listIndex = ref(0)

function openEdit(payload) {
  if (payload.sectionKey === 'basic') {
    showBasic.value = true
    return
  }
  listSection.value = payload.sectionKey
  listIndex.value = payload.index
  showList.value = true
}
</script>
