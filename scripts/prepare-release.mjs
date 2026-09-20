// Produce a deployment commit with the tested app, excluding CI workflow files.
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

const source = process.env.GITHUB_SHA;
if (!/^[a-f0-9]{40}$/.test(source || ''))
  throw new Error('GITHUB_SHA must identify the verified commit.');
const git = (args, env = process.env) =>
  execFileSync('git', args, { encoding: 'utf8', env }).trim();
if (git(['rev-parse', 'HEAD']) !== source)
  throw new Error('Checkout does not match the verified source.');
const parent = git(['rev-parse', 'origin/production']);
const manifestPath = 'public/deployment.json';
const priorFiles = git(['ls-tree', '--name-only', parent, manifestPath]);
if (priorFiles) {
  const prior = JSON.parse(git(['show', `${parent}:${manifestPath}`])).sourceCommit;
  if (!/^[a-f0-9]{40}$/.test(prior || '')) throw new Error('Invalid previous source record.');
  // Reject an older rerun or unrelated history instead of silently rolling back production.
  git(['merge-base', '--is-ancestor', prior, source]);
}
const temporary = mkdtempSync(path.join(tmpdir(), 'dishplay-release-'));
try {
  const env = { ...process.env, GIT_INDEX_FILE: path.join(temporary, 'index') };
  git(['read-tree', source], env);
  const workflows = git(['ls-files', '.github'], env).split('\n').filter(Boolean);
  if (workflows.length) git(['update-index', '--force-remove', '--', ...workflows], env);
  writeFileSync(manifestPath, JSON.stringify({ sourceCommit: source }) + '\n');
  git(['add', '--', manifestPath], env);
  const tree = git(['write-tree'], env);
  const author = git(['show', '-s', '--format=%an', source]);
  const email = git(['show', '-s', '--format=%ae', source]);
  const commit = git(
    ['commit-tree', tree, '-p', parent, '-m', `Deploy verified source ${source}`],
    {
      ...env,
      GIT_AUTHOR_NAME: author,
      GIT_AUTHOR_EMAIL: email,
      GIT_COMMITTER_NAME: author,
      GIT_COMMITTER_EMAIL: email,
    },
  );
  console.log(commit);
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
