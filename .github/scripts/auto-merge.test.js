const {test} = require('node:test');
const assert = require('node:assert/strict');
const merge = require('./auto-merge');

function fixture() {
  const pr = {number: 1, state: 'open', draft: false,
    user: {login: 'github-actions[bot]'},
    head: {sha: 'current', ref: 'auto/update-omnigent', repo: {full_name: 'owner/repo'}},
    merge_commit_sha: 'merge'};
  const runs = ['ci', 'sbom'].map((name, i) => ({id: i + 1,
    path: `.github/workflows/${name}.yml`, event: 'workflow_dispatch',
    status: 'completed', conclusion: 'success'}));
  const state = {pr, runs, checks: [], statuses: {total_count: 0}, merges: []};
  const rest = {
    pulls: {list: () => [state.pr], get: () => ({data: state.current || state.pr}),
      merge: args => {state.merges.push(args); return {data: {message: 'merged'}};}},
    actions: {listWorkflowRunsForRepo: () => state.runs},
    checks: {listForRef: () => state.checks},
    repos: {getCombinedStatusForRef: () => ({data: state.statuses})},
  };
  state.invoke = () => merge({
    github: {rest, paginate: async (method, args) => method(args)},
    context: {repo: {owner: 'owner', repo: 'repo'}, payload: {
      repository: {full_name: 'owner/repo'}, workflow_run: {head_sha: 'current'}}},
    core: {info() {}},
  });
  return state;
}

test('merges a trusted bot update using a SHA precondition after both gates pass', async () => {
  const f = fixture(); await f.invoke();
  assert.equal(f.merges.length, 1);
  assert.equal(f.merges[0].sha, 'current');
});
for (const [name, change] of Object.entries({
  'missing CI': f => {f.runs = [];},
  'failed CI': f => {f.runs[0].conclusion = 'failure';},
  'cancelled SBOM': f => {f.runs[1].conclusion = 'cancelled';},
  'pending CI': f => {f.runs[0].status = 'in_progress';},
  'newer failed rerun': f => {f.runs.push({...f.runs[0], id: 20, conclusion: 'failure'});},
  'pending extra check': f => {f.checks = [{name: 'external', status: 'queued'}];},
  'failed extra check': f => {f.checks = [{name: 'external', status: 'completed', conclusion: 'failure'}];},
  'failed commit status': f => {f.statuses = {total_count: 1, state: 'failure'};},
  'new PR revision': f => {f.current = {...f.pr, head: {...f.pr.head, sha: 'new'}};},
  'untrusted author': f => {f.pr.user.login = 'someone';},
  'unrecognized bot branch': f => {f.pr.head.ref = 'other';},
  'fork PR': f => {f.pr.head.repo.full_name = 'fork/repo';},
  'draft PR': f => {f.pr.draft = true;},
})) {
  test(`does not merge with ${name}`, async () => {
    const f = fixture(); change(f); await f.invoke(); assert.equal(f.merges.length, 0);
  });
}
test('accepts Dependabot update branches', async () => {
  const f = fixture(); f.pr.user.login = 'dependabot[bot]';
  f.pr.head.ref = 'dependabot/docker/fedora';
  await f.invoke(); assert.equal(f.merges.length, 1);
});
