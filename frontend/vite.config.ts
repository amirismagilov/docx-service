import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/** В Docker Compose прокси должен смотреть на сервис `api`, не на loopback контейнера `web`. */
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8080'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5175,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
})
