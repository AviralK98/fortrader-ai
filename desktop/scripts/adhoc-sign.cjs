/**
 * Ad-hoc sign the macOS app after packaging.
 *
 * Apple Silicon refuses to execute a Mach-O binary carrying no signature
 * at all. With `identity: null` electron-builder signs nothing, so
 * without this hook the app cannot start even on the machine that built
 * it. `codesign --sign -` buys the right to run.
 *
 * It buys nothing else. An ad-hoc signature is not a certificate and
 * identifies nobody, so Gatekeeper still rejects the app once macOS has
 * marked it as downloaded:
 *
 *   codesign --verify --deep --strict App.app   # passes
 *   spctl --assess --type execute App.app       # rejected
 *
 * Those two commands answer different questions -- whether the signature
 * is intact, and whether macOS will run the thing -- and only the second
 * one decides. A user who downloads the .dmg gets "is damaged and can't
 * be opened", with Move to Bin as the only button. Nothing in this file
 * can change that; see docs/development.md, "Gatekeeper rejects every
 * downloaded build". The .dmg ships READ ME FIRST.txt because of it.
 *
 * On --deep and what the verify below actually proves:
 *
 * --deep reaches nested code in the places macOS defines as code --
 * Frameworks, PlugIns, Helpers, XPCServices -- which covers the Electron
 * framework and helper apps. It does NOT reach the PyInstaller sidecar
 * under Contents/Resources, and `--verify --deep --strict` passes anyway
 * without having looked at it:
 *
 *   $ codesign --force --deep --sign - Bundle.app
 *   $ codesign -dv Bundle.app/Contents/Resources/backend/fortrader-backend
 *   ...: code object is not signed at all
 *   $ codesign --verify --deep --strict Bundle.app   # passes
 *
 * The sidecar runs regardless because PyInstaller ad-hoc signs its own
 * output -- all 135 Mach-O files in dist/fortrader-backend arrive signed.
 * So nothing is broken today, and the verification below is a real check
 * that the outer bundle got signed. It is simply not the guarantee about
 * nested code that it looks like.
 *
 * That gap becomes a real bug the day a Developer ID is bought:
 * notarisation requires every nested Mach-O to carry that identity, and
 * these would still carry PyInstaller's ad-hoc ones. Sign the sidecar
 * inside-out before switching identities.
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
  // whoever downloads it, so prove the outer signature took while the
  // build can still fail. Read the header before trusting --deep here.
  execFileSync('codesign', ['--verify', '--deep', '--strict', app], {
    stdio: 'inherit',
  });

  console.log('Ad-hoc signature verified.');
};
