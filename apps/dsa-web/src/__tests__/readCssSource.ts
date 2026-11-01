// vitest 會把 .css 的 ?raw 轉成空字串，守門測試要讀原文只能走 fs（型別見 node-fs.d.ts）。
import { readFileSync } from 'node:fs';

// vitest 有注入 __dirname；jsdom 下 new URL(import.meta.url) 取不到實際路徑。
declare const __dirname: string;

/** 回傳 src/index.css 的原始內容，只給測試用。 */
export const readIndexCss = (): string => readFileSync(`${__dirname}/../index.css`, 'utf-8');
