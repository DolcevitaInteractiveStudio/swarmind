import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import VueI18nPlugin from '@intlify/unplugin-vue-i18n/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [
    vue(),
    // Messages in src/i18n/*.json are compiled to functions at build time and vue-i18n is aliased
    // to its runtime-only build: no message compiler, no eval/new Function (CSP script-src 'self')
    VueI18nPlugin({
      include: [fileURLToPath(new URL('./src/i18n/*.json', import.meta.url))],
      runtimeOnly: true,
      compositionOnly: true,
      fullInstall: false,
      strictMessage: true,
      escapeHtml: false,
    }),
  ],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }
  },
  server: {
    port: 3000,
    proxy: {
      '/api': { target: 'http://localhost:5001', changeOrigin: true },
      '/socket.io': { target: 'http://localhost:5001', ws: true },
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    rollupOptions: {
      output: {
        assetFileNames: 'assets/[name]-[hash][extname]',
        chunkFileNames: 'assets/[name]-[hash].js',
        entryFileNames: 'assets/[name]-[hash].js',
      }
    }
  }
})
