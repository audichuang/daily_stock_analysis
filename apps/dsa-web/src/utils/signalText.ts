/**
 * 決策訊號的條列欄位（觸發條件、觀察條件、風險摘要）在應用庫裡是 JSON 陣列「字串」
 * （例如 `["守住 299", "量縮就減碼"]`），API 也原樣回字串。畫面直接印就會出現方括號與引號。
 *
 * 這裡只在整段是合法的 JSON 陣列時才拆；一般句子（含以 `[` 開頭但不是陣列的文字）原樣保留。
 */
export function parseSignalList(value: unknown): string[] | null {
  if (Array.isArray(value)) return toItems(value);
  if (typeof value !== 'string') return null;
  const text = value.trim();
  if (!text.startsWith('[') || !text.endsWith(']')) return null;
  try {
    const parsed: unknown = JSON.parse(text);
    return Array.isArray(parsed) ? toItems(parsed) : null;
  } catch {
    return null;
  }
}

function toItems(values: unknown[]): string[] {
  return values
    .map((v) => (typeof v === 'string' ? v : v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v)))
    .map((v) => v.trim())
    .filter(Boolean);
}

/** 單行顯示（摘要、行內文字）：陣列以「；」接起來；不是陣列就原樣（去頭尾空白）。 */
export function formatSignalText(value: string | null | undefined, separator = '；'): string | null {
  const list = parseSignalList(value);
  if (list) return list.length ? list.join(separator) : null;
  const text = value?.trim();
  return text ? text : null;
}
