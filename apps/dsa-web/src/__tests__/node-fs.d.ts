// 專案沒裝 @types/node，只宣告測試用到的這一支。
declare module 'node:fs' {
  export function readFileSync(path: string, encoding: 'utf-8'): string;
}
