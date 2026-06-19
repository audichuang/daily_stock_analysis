const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const test = require('node:test');

const {
  notarizeMacBuild,
  resolveAppPath,
  resolveNotarizeAuth,
} = require('../scripts/notarize');

function buildContext(appOutDir) {
  return {
    electronPlatformName: 'darwin',
    appOutDir,
    packager: {
      appInfo: {
        appId: 'com.daily-stock-analysis.desktop',
        productFilename: 'Daily Stock Analysis',
      },
    },
  };
}

test('resolveNotarizeAuth supports Apple ID credentials', () => {
  const auth = resolveNotarizeAuth({
    APPLE_ID: 'maintainer@example.com',
    APPLE_APP_SPECIFIC_PASSWORD: 'app-password',
    APPLE_TEAM_ID: 'TEAM123456',
  });

  assert.equal(auth.mode, 'apple-id');
  assert.deepEqual(auth.options, {
    appleId: 'maintainer@example.com',
    appleIdPassword: 'app-password',
    teamId: 'TEAM123456',
  });
});

test('resolveNotarizeAuth supports App Store Connect API key credentials first', () => {
  const auth = resolveNotarizeAuth({
    APPLE_ID: 'maintainer@example.com',
    APPLE_APP_SPECIFIC_PASSWORD: 'app-password',
    APPLE_TEAM_ID: 'TEAM123456',
    APPLE_API_KEY: '/tmp/AuthKey.p8',
    APPLE_API_KEY_ID: 'KEY1234567',
    APPLE_API_ISSUER: 'issuer-id',
  });

  assert.equal(auth.mode, 'api-key');
  assert.deepEqual(auth.options, {
    appleApiKey: '/tmp/AuthKey.p8',
    appleApiKeyId: 'KEY1234567',
    appleApiIssuer: 'issuer-id',
  });
});

test('notarizeMacBuild skips unsigned local macOS builds by default', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dsa-notarize-skip-'));
  const result = await notarizeMacBuild(buildContext(tempRoot), { env: {} });

  assert.deepEqual(result, { skipped: true, reason: 'missing-credentials' });
});

test('notarizeMacBuild fails missing credentials when notarization is required', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dsa-notarize-required-'));

  await assert.rejects(
    notarizeMacBuild(buildContext(tempRoot), {
      env: { DSA_MAC_NOTARIZE_REQUIRED: 'true' },
    }),
    /macOS notarization credentials are missing/
  );
});

test('notarizeMacBuild submits the signed app bundle when credentials exist', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dsa-notarize-submit-'));
  const context = buildContext(tempRoot);
  const appPath = resolveAppPath(context);
  fs.mkdirSync(appPath, { recursive: true });

  const calls = [];
  const result = await notarizeMacBuild(context, {
    env: {
      APPLE_ID: 'maintainer@example.com',
      APPLE_APP_SPECIFIC_PASSWORD: 'app-password',
      APPLE_TEAM_ID: 'TEAM123456',
    },
    notarizeImpl: async (payload) => {
      calls.push(payload);
    },
  });

  assert.deepEqual(result, { skipped: false, appPath, mode: 'apple-id' });
  assert.deepEqual(calls, [
    {
      appBundleId: 'com.daily-stock-analysis.desktop',
      appPath,
      appleId: 'maintainer@example.com',
      appleIdPassword: 'app-password',
      teamId: 'TEAM123456',
    },
  ]);
});
