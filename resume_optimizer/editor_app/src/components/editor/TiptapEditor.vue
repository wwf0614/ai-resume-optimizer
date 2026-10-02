<template>
  <div class="ed-richtext">
    <div class="tiptap-toolbar" v-if="editor">
      <button :class="{ active: editor.isActive('bold') }" @click="editor.chain().focus().toggleBold().run()"><b>B</b></button>
      <button :class="{ active: editor.isActive('italic') }" @click="editor.chain().focus().toggleItalic().run()"><i>I</i></button>
      <button :class="{ active: editor.isActive('bulletList') }" @click="editor.chain().focus().toggleBulletList().run()">• 列表</button>
      <button :class="{ active: editor.isActive('orderedList') }" @click="editor.chain().focus().toggleOrderedList().run()">1. 列表</button>
      <button @click="editor.chain().focus().undo().run()">↶</button>
      <button @click="editor.chain().focus().redo().run()">↷</button>
    </div>
    <editor-content :editor="editor" class="tiptap-body" :data-placeholder="placeholder" />
  </div>
</template>

<script setup>
import { onBeforeUnmount, watch } from 'vue'
import { useEditor, EditorContent } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '请输入内容…' }
})
const emit = defineEmits(['update:modelValue'])

const editor = useEditor({
  content: props.modelValue || '',
  extensions: [
    StarterKit,
    Placeholder.configure({ placeholder: props.placeholder })
  ],
  onUpdate: ({ editor }) => {
    emit('update:modelValue', editor.getHTML())
  }
})

watch(() => props.modelValue, (val) => {
  if (editor.value && val !== editor.value.getHTML()) {
    editor.value.commands.setContent(val || '', false)
  }
})

onBeforeUnmount(() => {
  if (editor.value) editor.value.destroy()
})
</script>
