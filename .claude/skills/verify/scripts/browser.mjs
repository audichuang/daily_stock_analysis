#!/usr/bin/env node
// 由 ego-browser nodejs 匯入；跨功能共用同一個 TaskSpace，最後才 finish。
export async function applicationSnapshot(page) {
  let snapshot = await page.snapshot({ scope: "full_page" });
  // 真登入後出現的 1Password Save login iframe 會帶私人資料；禁止保存或回傳。
  if (snapshot.includes('heading\n              text "Save login?"') || snapshot.includes('text "Save login?"')) {
    throw new Error("外部密碼管理器提示仍開啟；先關閉提示，再取得應用證據。禁止列印原始完整 snapshot。");
  }
  // 登入驗證會填暫時密碼；AX 若帶出值，保存前遮蔽，畫面仍由密碼欄原生掩碼呈現。
  const passwords = await page.evaluate(() => [...document.querySelectorAll('input[type="password"]')].map(node => node.value).filter(Boolean));
  for (const value of passwords) snapshot = snapshot.split(value).join("[PASSWORD_REDACTED]");
  return snapshot;
}

export async function openRun(directory) {
  const fs = await import("node:fs/promises");
  const meta = JSON.parse(await fs.readFile(`${directory}/instance.json`, "utf8"));
  const task = await taskSpace(meta.browser_space_id);
  const page = task.page("p1");
  const append = async (filename, value) => {
    await fs.appendFile(`${directory}/${filename}`, `${JSON.stringify(value)}\n`);
  };
  const snapshot = () => applicationSnapshot(page);
  const capture = async (name, fullPage = true) => {
    await fs.writeFile(`${directory}/${name}.txt`, await snapshot());
    await page.screenshot({ path: `${directory}/${name}.png`, fullPage });
  };
  const act = async (description, operation) => {
    const started = new Date().toISOString();
    try {
      const receipt = await operation();
      await append("actions.jsonl", { started, finished: new Date().toISOString(), description, receipt });
      return receipt;
    } catch (error) {
      await append("actions.jsonl", { started, finished: new Date().toISOString(), description, error: String(error) });
      await capture(`failure-${Date.now()}`);
      throw error;
    }
  };
  const api = async (name, route, format = "json") => {
    const response = await page.fetch(route);
    const evidence = { status: response.status, url: response.url, body: response.body };
    await fs.writeFile(`${directory}/${name}.json`, JSON.stringify(evidence, null, 2));
    if (response.status !== 200) throw new Error(`${route}: HTTP ${response.status}; response retained`);
    return format === "text" ? response.body : JSON.parse(response.body);
  };
  const mark = async (feature, status, detail) => append("coverage.jsonl", { feature, status, detail, at: new Date().toISOString() });
  return { fs, meta, task, page, snapshot, capture, act, api, mark, directory };
}
