<template>
  <aside class="ed-right">
    <div class="ed-tabs">
      <button class="ed-tab" :class="{ active: tab === 'modules' }" @click="tab = 'modules'">信息模块</button>
      <button class="ed-tab" :class="{ active: tab === 'sort' }" @click="tab = 'sort'">排序设置</button>
    </div>
    <div class="ed-panel-body">
      <div v-show="tab === 'modules'">
        <div v-for="m in moduleDefs" :key="m.key" class="module-item" :class="{ active: store.moduleVisibility[m.key] }"
             @click="$emit('open-edit', { sectionKey: m.key, index: 0 })">
          <div class="item-left">
            <span>{{ m.icon }}</span>
            <span>{{ m.label }}</span>
          </div>
          <el-switch :model-value="store.moduleVisibility[m.key]" @change.stop="store.toggleModule(m.key)" />
        </div>
      </div>
      <div v-show="tab === 'sort'">
        <draggable v-model="order" item-key="key" handle=".drag-ico" animation="220"
                   ghost-class="sortable-ghost" chosen-class="sortable-chosen">
          <template #item="{ element }">
            <div class="module-sort-item">
              <span class="item-left"><span>{{ iconOf(element) }}</span><span>{{ labelOf(element) }}</span></span>
              <span class="drag-ico">⠿</span>
            </div>
          </template>
        </draggable>
        <p style="font-size:12px;color:#999;margin-top:12px">拖拽右侧手柄调整模块在简历中的显示顺序</p>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { ref, computed } from 'vue'
import draggable from 'vuedraggable'
import { useResumeStore } from '../store/resumeStore'

const store = useResumeStore()
const tab = ref('modules')

const moduleDefs = [
  { key: 'basic', label: '基本信息', icon: '👤' },
  { key: 'job', label: '意向职位', icon: '🎯' },
  { key: 'education', label: '教育背景', icon: '🎓' },
  { key: 'work', label: '工作经验', icon: '💼' },
  { key: 'project', label: '项目经历', icon: '🚀' },
  { key: 'internship', label: '实习经历', icon: '🏢' },
  { key: 'campus', label: '校园经历', icon: '🏛️' },
  { key: 'skills', label: '特长技能', icon: '⚡' },
  { key: 'honors', label: '荣誉证书', icon: '🏆' },
  { key: 'selfEval', label: '自我评价', icon: '✨' },
  { key: 'hobbies', label: '兴趣爱好', icon: '💡' },
  { key: 'custom', label: '自定义', icon: '📝' }
]

const order = computed({
  get: () => store.modulesOrder,
  set: (val) => store.updateModulesOrder(val)
})

function labelOf(key) { return (moduleDefs.find(m => m.key === key) || {}).label || key }
function iconOf(key) { return (moduleDefs.find(m => m.key === key) || {}).icon || '•' }
</script>
