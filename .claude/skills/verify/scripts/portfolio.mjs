#!/usr/bin/env node
// 只經 ego-browser nodejs 執行；TaskSpace 與 Page 由其 runtime 提供。
import { applicationSnapshot } from "./browser.mjs";

export async function verifyPortfolio(runDirectory) {
  const fs = await import("node:fs/promises");
  const assert = (await import("node:assert/strict")).default;
  const meta = JSON.parse(await fs.readFile(`${runDirectory}/instance.json`, "utf8"));
  const task = await taskSpace(meta.browser_space_id ?? `DSA verify ${meta.account_name}`);
  const page = task.page("p1");
  const actions = [];
  const record = async (action, execute) => {
    const receipt = await execute();
    actions.push({ at: new Date().toISOString(), action, receipt: receipt ?? null });
    await fs.writeFile(`${runDirectory}/actions.json`, JSON.stringify(actions, null, 2));
  };
  const capture = async (name) => {
    await fs.writeFile(`${runDirectory}/${name}.txt`, await applicationSnapshot(page));
    await page.screenshot({ path: `${runDirectory}/${name}.png`, fullPage: true });
  };
  await fs.writeFile(`${runDirectory}/browser-space.json`, JSON.stringify({ spaceId: task.spaceId, page: page.label }));
  await record("前往持股帳本", () => page.goto(`${meta.url}/portfolio`));
  await page.waitForSelector('input[placeholder="账户名称（必填）"]', { state: "visible" });
  await capture("01-empty");
  await record("填寫測試帳戶名稱", () => page.fill('input[placeholder="账户名称（必填）"]', meta.account_name));
  await record("填寫測試券商", () => page.fill('input[placeholder="券商（可选，如 Demo/华泰）"]', "Verification"));
  await record("設定同幣別 CNY", () => page.fill('input[placeholder="基准币（如 CNY/USD/HKD）"]', "CNY"));
  await capture("02-account-input");
  await record("建立帳戶", () => page.click("loc=role:button[name='创建账户']", { label: "建立隔離測試帳戶" }));
  await page.waitForFunction((name) => [...document.querySelectorAll("option")].some((node) => node.textContent.includes(name)), meta.account_name);
  await record("填寫入金金額", () => page.fill('input[placeholder="金额"]', "12345"));
  const eventDate = await page.evaluate(() => document.querySelector('input[placeholder="金额"]').closest("form").querySelector('input[type="date"]').value);
  await capture("03-cash-input");
  await record("提交資金流水", () => page.click("loc=role:button[name='提交资金流水']", { label: "提交測試入金流水" }));
  await page.waitForFunction(() => document.body.innerText.includes("12,345"));
  await record("切換資金流水紀錄", () => page.selectOption('select:has(option[value="cash"])', "cash"));
  await page.waitForFunction(() => [...document.querySelectorAll("div.min-w-0")].some((node) => /流入\s+12345\s+CNY/.test(node.textContent)));
  await capture("04-saved");
  await record("重新整理核對持久化", () => page.reload());
  await page.waitForFunction((name) => document.body.innerText.includes("12,345") && [...document.querySelectorAll("option")].some((node) => node.textContent.includes(name)), meta.account_name);
  await capture("05-reloaded");
  const accountsResponse = await page.fetch("/api/v1/portfolio/accounts");
  await fs.writeFile(`${runDirectory}/api-accounts-response.json`, JSON.stringify(accountsResponse, null, 2));
  const cashResponse = await page.fetch("/api/v1/portfolio/cash-ledger");
  await fs.writeFile(`${runDirectory}/api-cash-response.json`, JSON.stringify(cashResponse, null, 2));
  assert.equal(accountsResponse.status, 200);
  assert.equal(cashResponse.status, 200);
  const accounts = JSON.parse(accountsResponse.body);
  const cash = JSON.parse(cashResponse.body);
  await fs.writeFile(`${runDirectory}/api-accounts.json`, JSON.stringify(accounts, null, 2));
  await fs.writeFile(`${runDirectory}/api-cash.json`, JSON.stringify(cash, null, 2));
  assert.equal(accounts.accounts.length, 1);
  assert.equal(accounts.accounts[0].name, meta.account_name);
  assert.equal(accounts.accounts[0].base_currency, "CNY");
  // API 契約變更使斷言失敗時，仍保留原始回應供調查。
  assert.equal(cash.total, 1);
  assert.equal(cash.items[0].account_id, accounts.accounts[0].id);
  assert.equal(cash.items[0].amount, 12345);
  assert.equal(cash.items[0].direction, "in");
  assert.equal(cash.items[0].currency, "CNY");
  assert.equal(cash.items[0].event_date, eventDate);
  await fs.writeFile(`${runDirectory}/browser-result.json`, JSON.stringify({
    feature: "portfolio", entries: ["/portfolio"], passed: ["account-create", "cash-in", "reload-persistence"],
    accountId: accounts.accounts[0].id, spaceId: task.spaceId, at: new Date().toISOString(),
  }, null, 2));
  console.log(await applicationSnapshot(page));
  await task.finish({ keep: [] });
  await fs.writeFile(`${runDirectory}/browser-cleanup.json`, JSON.stringify({ finished: true, spaceId: task.spaceId }));
  console.log({ passed: true, evidence: runDirectory });
}
