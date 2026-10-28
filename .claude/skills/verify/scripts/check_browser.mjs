#!/usr/bin/env node
// 使用合成 Page 邊界與自有暫存檔，不啟動瀏覽器、不讀既有快照。
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import * as fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import vm from "node:vm";

const healthySnapshot = 'document\n  text "DSA helper check"\n  text "12,345 CNY"\n';
const syntheticPrivate = "synthetic-password-manager-private-sentinel";
const popupSnapshot = `${healthySnapshot}iframe\n  heading\n              text "Save login?"\n  text "${syntheticPrivate}"\n`;
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aM1sAAAAASUVORK5CYII=",
  "base64",
);

async function withPage(openRun, snapshotText, passwords, verify) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "dsa-browser-helper-"));
  const calls = { snapshot: 0, evaluate: 0, screenshot: [] };
  const previousTaskSpace = Object.getOwnPropertyDescriptor(globalThis, "taskSpace");
  const page = {
    async snapshot(options) {
      assert.deepEqual(options, { scope: "full_page" });
      calls.snapshot += 1;
      return snapshotText;
    },
    async evaluate(operation) {
      calls.evaluate += 1;
      // 執行真正的頁面函式；document 僅回傳測試擁有的合成密碼欄。
      return vm.runInNewContext(`(${operation.toString()})()`, {
        document: {
          querySelectorAll(selector) {
            assert.equal(selector, 'input[type="password"]');
            return passwords.map((value) => ({ value }));
          },
        },
      });
    },
    async screenshot(options) {
      assert.equal(path.dirname(options.path), directory);
      calls.screenshot.push(options);
      await fs.writeFile(options.path, png);
    },
  };
  Object.defineProperty(globalThis, "taskSpace", {
    configurable: true,
    value: async (spaceId) => {
      assert.equal(spaceId, 731);
      return { page(label) { assert.equal(label, "p1"); return page; } };
    },
  });
  try {
    await fs.writeFile(path.join(directory, "instance.json"), JSON.stringify({ browser_space_id: 731 }));
    const run = await openRun(directory);
    await verify({ run, directory, calls });
  } finally {
    if (previousTaskSpace) Object.defineProperty(globalThis, "taskSpace", previousTaskSpace);
    else delete globalThis.taskSpace;
    await fs.rm(directory, { recursive: true, force: true });
  }
}

async function verifyHealthyCapture(openRun) {
  await withPage(openRun, healthySnapshot, [], async ({ run, directory, calls }) => {
    assert.equal(await run.snapshot(), healthySnapshot);
    await run.capture("healthy", false);
    assert.equal(await fs.readFile(path.join(directory, "healthy.txt"), "utf8"), healthySnapshot);
    assert.deepEqual(await fs.readFile(path.join(directory, "healthy.png")), png);
    assert.deepEqual(calls.screenshot, [{ path: path.join(directory, "healthy.png"), fullPage: false }]);
  });
}

async function verifyBlockedPopup(openRun) {
  await withPage(openRun, popupSnapshot, ["synthetic-login-password"], async ({ run, directory, calls }) => {
    const safeError = (error) => {
      assert.ok(error instanceof Error);
      assert.ok(!error.message.includes(syntheticPrivate), "拒絕訊息不可回傳合成私人欄位");
      assert.ok(!error.message.includes(popupSnapshot), "拒絕訊息不可回傳原始 snapshot");
      return true;
    };
    await assert.rejects(() => run.snapshot(), safeError);
    await assert.rejects(() => run.capture("blocked"), safeError);
    assert.deepEqual(await fs.readdir(directory), ["instance.json"], "被拒後不可寫 TXT 或 PNG");
    assert.equal(calls.screenshot.length, 0, "被拒後不可呼叫 screenshot");
    assert.equal(calls.evaluate, 0, "外部提示應在讀取應用密碼欄之前被拒");
  });
}

async function mutatedModule(source, condition) {
  // 只改記憶體中的原始 guard；未命中就失敗，避免 mutation 沒有真正改到修法。
  const guard = /^([ \t]*)if \(snapshot\.includes\([^\n]+\) \{/m;
  const match = source.match(guard);
  assert.ok(match && match[0].includes("Save login?"), "mutation 必須命中密碼管理器 guard");
  const modified = source.replace(guard, `$1if (${condition}) {`);
  return import(`data:text/javascript;base64,${Buffer.from(modified).toString("base64")}`);
}

async function main() {
  const outputIndex = process.argv.indexOf("--output-dir");
  assert.ok(outputIndex >= 0 && process.argv[outputIndex + 1], "需要 --output-dir <本輪證據目錄>");
  const output = path.resolve(process.argv[outputIndex + 1]);
  await fs.mkdir(output, { recursive: true });
  const subject = new URL("./browser.mjs", import.meta.url);
  const source = await fs.readFile(subject, "utf8");
  const { openRun } = await import(subject.href);
  const started = new Date().toISOString();
  const results = [];
  const mutations = [];
  const checks = [
    ["正常應用 snapshot 可回傳並保存 TXT／PNG", () => verifyHealthyCapture(openRun)],
    ["密碼欄值在回傳與保存前遮蔽，其餘應用文字保留", async () => {
      const passwords = ["synthetic-password-one", "synthetic-password-two", ""];
      const text = `${healthySnapshot}value "${passwords[0]}"\nagain "${passwords[0]}"\nvalue "${passwords[1]}"\n`;
      await withPage(openRun, text, passwords, async ({ run, directory, calls }) => {
        const safe = await run.snapshot();
        await run.capture("password");
        const saved = await fs.readFile(path.join(directory, "password.txt"), "utf8");
        assert.equal(saved, safe);
        for (const password of passwords.filter(Boolean)) assert.ok(!safe.includes(password));
        assert.equal(safe.split("[PASSWORD_REDACTED]").length - 1, 3);
        assert.ok(safe.includes(healthySnapshot));
        assert.equal(calls.screenshot.length, 1);
      });
    }],
    ["Save login 提示被拒且不回傳原文、不寫證據、不截圖", () => verifyBlockedPopup(openRun)],
    ["移除 guard 的記憶體 mutation 會使隱私守門變紅", async () => {
      const mutated = await mutatedModule(source, "false");
      await assert.rejects(() => verifyBlockedPopup(mutated.openRun), { code: "ERR_ASSERTION" });
      mutations.push({ mutation: "removed_guard", detected: true });
    }],
    ["過度拒絕正常應用的記憶體 mutation 會使正向守門變紅", async () => {
      const mutated = await mutatedModule(source, "true");
      await assert.rejects(() => verifyHealthyCapture(mutated.openRun));
      mutations.push({ mutation: "blocked_all_healthy", detected: true });
    }],
  ];
  for (const [name, operation] of checks) {
    try {
      await operation();
      results.push({ name, passed: true });
    } catch (error) {
      results.push({ name, passed: false, error: String(error.stack || error) });
    }
  }
  const failed = results.filter((result) => !result.passed).length;
  const summary = {
    command: [process.execPath, ...process.argv.slice(1)],
    started_at: started, finished_at: new Date().toISOString(),
    subject_sha256: createHash("sha256").update(source).digest("hex"),
    collected: checks.length, run: results.length, passed: results.length - failed, failed, skipped: 0,
    mutation_checks: mutations, exit_code: failed ? 1 : 0,
    scope: "合成 Page SDK 邊界與自有暫存檔；沒有 browser／網路／正式設定或私人快照",
  };
  await fs.writeFile(path.join(output, "tests.log"), results.map((result) => (
    `${result.passed ? "PASS" : "FAIL"} ${result.name}${result.error ? `\n${result.error}` : ""}\n`
  )).join(""));
  await fs.writeFile(path.join(output, "results.json"), `${JSON.stringify({ ...summary, tests: results }, null, 2)}\n`);
  console.log(JSON.stringify(summary, null, 2));
  process.exitCode = summary.exit_code;
}

await main();
