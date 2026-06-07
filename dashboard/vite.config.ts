import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Local dev: port-forward each service first, then `npm run dev`
//   kubectl port-forward -n phoenix-system svc/phoenix-graph   8080:80
//   kubectl port-forward -n phoenix-system svc/phoenix-chaos   8082:80
//   kubectl port-forward -n phoenix-system svc/phoenix-faultlib 8081:80
//   kubectl port-forward -n phoenix-system svc/phoenix-sim     8083:80
//   kubectl port-forward -n phoenix-system svc/phoenix-agent   8084:80
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api/graph': {
        target: 'http://localhost:8080',
        rewrite: path => path.replace(/^\/api\/graph/, ''),
        changeOrigin: true,
      },
      '/api/chaos': {
        target: 'http://localhost:8082',
        rewrite: path => path.replace(/^\/api\/chaos/, ''),
        changeOrigin: true,
      },
      '/api/faultlib': {
        target: 'http://localhost:8081',
        rewrite: path => path.replace(/^\/api\/faultlib/, ''),
        changeOrigin: true,
      },
      '/api/sim': {
        target: 'http://localhost:8083',
        rewrite: path => path.replace(/^\/api\/sim/, ''),
        changeOrigin: true,
      },
      '/api/agent': {
        target: 'http://localhost:8084',
        rewrite: path => path.replace(/^\/api\/agent/, ''),
        changeOrigin: true,
      },
    },
  },
})
