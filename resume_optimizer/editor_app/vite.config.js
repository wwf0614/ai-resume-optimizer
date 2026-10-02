import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: '/static/editor_new/',
  plugins: [vue()],
  build: {
    outDir: '../static/editor_new',
    emptyOutDir: true
  }
})
