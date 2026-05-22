import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const packageJson = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf-8'),
) as { version?: string }
const buildTime = new Date().toISOString()
const getVendorPackage = (id: string): string | undefined => {
  const match = id.match(/[\\/](?:node_modules)[\\/](@[^\\/]+[\\/][^\\/]+|[^\\/]+)(?=[\\/]|$)/);
  if (!match || match.length < 2) {
    return undefined;
  }
  return match[1];
}

// https://vite.dev/config/
export default defineConfig({
  define: {
    __APP_PACKAGE_VERSION__: JSON.stringify(packageJson.version ?? '0.0.0'),
    __APP_BUILD_TIME__: JSON.stringify(buildTime),
  },
  plugins: [
    react({
      babel: {
        plugins: [['babel-plugin-react-compiler']],
      },
    }),
  ],
  server: {
    host: '0.0.0.0',  // 允许公网访问
    port: 5173,       // 默认端口
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    // 打包输出到项目根目录的 static 文件夹
    outDir: path.resolve(__dirname, '../../static'),
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: (id: string) => {
          const packageName = getVendorPackage(id);
          if (!packageName) {
            return undefined;
          }
          if (packageName === 'react' || packageName === 'react-dom') {
            return 'vendor-react';
          }
          if (packageName === 'react-router' || packageName === 'react-router-dom') {
            return 'vendor-router';
          }
          if (packageName === 'motion') {
            return 'vendor-motion';
          }
          if (packageName === 'lucide-react' || packageName === '@remixicon/react') {
            return 'vendor-icons';
          }
          if (packageName === 'recharts' || packageName.startsWith('d3-')) {
            return 'vendor-charts';
          }
          if (
            packageName === 'react-markdown'
            || packageName === 'remark-gfm'
            || packageName === 'unified'
            || packageName === 'micromark'
            || packageName.startsWith('remark-')
            || packageName.startsWith('mdast')
            || packageName.startsWith('hast')
          ) {
            return 'vendor-markdown';
          }

          return undefined;
        },
      },
    },
  },
})
