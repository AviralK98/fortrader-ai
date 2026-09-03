/**
 * Ad-hoc sign the macOS app after packaging.
 *
 * Apple Silicon refuses to run a Mach-O binary carrying no signature at
 * all. With `identity: null` electron-builder skips signing entirely, so
 * the downloaded app fails with "is damaged and can't be opened" — a
 * message that describes neither the cause nor anything the user can
 * act on, and which leaves Move to Trash as the only offered option.
 *
 * An ad-hoc signature (`codesign --sign -`) is not a certificate and
 * proves nothing about who built the app. It only satisfies the
 * requirement that the code be signed *somehow*, which downgrades that
 * dead end to the ordinary "unidentified developer" prompt that
 * right-click → Open can get past.
 *
 * Removing that prompt as well needs a real Developer ID and
 * notarisation. This is the part that can be done for nothing.
 *
 * The app bundles the PyInstaller sidecar under Contents/Resources, so
 * the signature has to cover nested code; --deep does that, and the
 * verification below fails the build rather than letting an unsigned
 * bundle reach a release quietly.
 */

const { execFileSync } = require('node:child_process');
const { join } = require('node:path');

exports.default = async function adhocSign(context) {
  if (context.electronPlatformName !== 'darwin') return;

  const app = join(
    context.appOutDir,
    `${context.packager.appInfo.productFilename}.app`,
  );

  console.log(`Ad-hoc signing ${app}`);

  execFileSync(
    'codesign',
    ['--force', '--deep', '--sign', '-', '--timestamp=none', app],
    { stdio: 'inherit' },
  );

  // An unsigned bundle that reaches a release is only discovered by
  // whoever downloads it, so prove the signature took while the build
  // can still fail.
  execFileSync('codesign', ['--verify', '--deep', '--strict', app], {
    stdio: 'inherit',
  });

  console.log('Ad-hoc signature verified.');
};
