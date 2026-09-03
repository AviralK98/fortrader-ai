import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { isNewerVersion } from '../main/updater';

describe('isNewerVersion', () => {
  it('recognises a later patch', () => {
    expect(isNewerVersion('0.2.3', '0.2.2')).toBe(true);
  });

  it('treats an identical version as not newer', () => {
    expect(isNewerVersion('0.2.2', '0.2.2')).toBe(false);
  });

  it('treats an older version as not newer', () => {
    expect(isNewerVersion('0.2.1', '0.2.2')).toBe(false);
  });

  it('compares numerically, not as text', () => {
    // The one that bites: "0.10.0" sorts before "0.9.0" as a string, so
    // a released update would look older than the installed build and
    // never be offered.
    expect(isNewerVersion('0.10.0', '0.9.0')).toBe(true);
    expect(isNewerVersion('0.9.0', '0.10.0')).toBe(false);
  });

  it('compares major before minor', () => {
    expect(isNewerVersion('1.0.0', '0.99.99')).toBe(true);
  });

  it('tolerates a leading v, as GitHub tags carry one', () => {
    expect(isNewerVersion('v0.2.3', '0.2.2')).toBe(true);
  });

  it('ignores a pre-release suffix rather than misreading it', () => {
    expect(isNewerVersion('0.3.0-beta.1', '0.2.9')).toBe(true);
  });

  it('does not crash on a malformed tag', () => {
    expect(isNewerVersion('', '0.2.2')).toBe(false);
    expect(isNewerVersion('not-a-version', '0.2.2')).toBe(false);
  });
});

describe('release feed', () => {
  it('checks the same repository the app is published to', () => {
    // macOS reads GitHub directly instead of going through Squirrel, so
    // it carries its own copy of the owner and repo. If those drift from
    // the publish block, macOS quietly polls a repository that is not
    // shipping the app and never sees an update.
    const config = readFileSync(
      join(__dirname, '..', 'electron-builder.yml'),
      'utf-8',
    );
    const source = readFileSync(
      join(__dirname, '..', 'main', 'updater.ts'),
      'utf-8',
    );

    const configured = {
      owner: /^\s*owner:\s*(\S+)/m.exec(config)?.[1],
      repo: /^\s*repo:\s*(\S+)/m.exec(config)?.[1],
    };

    expect(configured.owner).toBeDefined();
    expect(configured.repo).toBeDefined();

    expect(source).toContain(`REPO_OWNER = '${configured.owner}'`);
    expect(source).toContain(`REPO_NAME = '${configured.repo}'`);
  });
});
