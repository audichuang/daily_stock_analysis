const fs = require('fs');
const path = require('path');

function isTruthy(value) {
  return ['1', 'true', 'yes', 'on'].includes(String(value || '').trim().toLowerCase());
}

function resolveAppPath(context) {
  const productFilename = context?.packager?.appInfo?.productFilename;
  if (!context?.appOutDir || !productFilename) {
    throw new Error('Cannot resolve macOS app bundle path from electron-builder context.');
  }
  return path.join(context.appOutDir, `${productFilename}.app`);
}

function resolveNotarizeAuth(env = process.env) {
  if (env.APPLE_API_KEY && env.APPLE_API_KEY_ID && env.APPLE_API_ISSUER) {
    return {
      mode: 'api-key',
      options: {
        appleApiKey: env.APPLE_API_KEY,
        appleApiKeyId: env.APPLE_API_KEY_ID,
        appleApiIssuer: env.APPLE_API_ISSUER,
      },
    };
  }

  if (env.APPLE_ID && env.APPLE_APP_SPECIFIC_PASSWORD && env.APPLE_TEAM_ID) {
    return {
      mode: 'apple-id',
      options: {
        appleId: env.APPLE_ID,
        appleIdPassword: env.APPLE_APP_SPECIFIC_PASSWORD,
        teamId: env.APPLE_TEAM_ID,
      },
    };
  }

  return { mode: 'none', options: null };
}

async function notarizeMacBuild(context, options = {}) {
  if (context?.electronPlatformName && context.electronPlatformName !== 'darwin') {
    return { skipped: true, reason: 'non-macos' };
  }

  const env = options.env || process.env;
  const auth = resolveNotarizeAuth(env);
  const appPath = resolveAppPath(context);
  const required = isTruthy(env.DSA_MAC_NOTARIZE_REQUIRED);

  if (!auth.options) {
    const message = 'macOS notarization credentials are missing; skipping notarization.';
    if (required) {
      throw new Error(
        `${message} Provide APPLE_ID/APPLE_APP_SPECIFIC_PASSWORD/APPLE_TEAM_ID or APPLE_API_KEY/APPLE_API_KEY_ID/APPLE_API_ISSUER.`
      );
    }
    console.log(`[notarize] ${message}`);
    return { skipped: true, reason: 'missing-credentials' };
  }

  if (!fs.existsSync(appPath)) {
    throw new Error(`macOS app bundle not found for notarization: ${appPath}`);
  }

  const notarizeImpl = options.notarizeImpl || require('@electron/notarize').notarize;
  const appBundleId = context?.packager?.appInfo?.appId || 'com.daily-stock-analysis.desktop';

  console.log(`[notarize] Submitting ${appPath} with ${auth.mode} credentials.`);
  await notarizeImpl({
    appBundleId,
    appPath,
    ...auth.options,
  });
  console.log(`[notarize] Notarization completed for ${appPath}.`);
  return { skipped: false, appPath, mode: auth.mode };
}

module.exports = notarizeMacBuild;
module.exports.isTruthy = isTruthy;
module.exports.resolveAppPath = resolveAppPath;
module.exports.resolveNotarizeAuth = resolveNotarizeAuth;
module.exports.notarizeMacBuild = notarizeMacBuild;
