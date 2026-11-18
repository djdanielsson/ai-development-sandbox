// Executed from the default branch only. Never load code or artifacts from a PR.
module.exports = async ({github, context, core}) => {
  const {owner, repo} = context.repo;
  const run = context.payload.workflow_run;
  const branches = new Set([
    'auto/update-cli-tools', 'auto/update-extensions', 'auto/update-ohmyzsh',
    'auto/update-prek', 'auto/update-github-ssh-keys', 'auto/update-omnigent',
  ]);
  const prs = await github.paginate(github.rest.pulls.list, {
    owner, repo, state: 'open', base: 'main', per_page: 100,
  });
  for (const pr of prs) {
    if (pr.draft || pr.head.repo?.full_name !== context.payload.repository.full_name ||
        pr.head.sha !== run.head_sha) continue;
    const author = pr.user.login;
    if (!(author === 'dependabot[bot]' ||
          (author === 'github-actions[bot]' && branches.has(pr.head.ref)))) continue;

    // Require both workflows, even if checks have not registered yet. Only
    // consider the newest run of each workflow for this exact PR revision.
    const runs = await github.paginate(github.rest.actions.listWorkflowRunsForRepo, {
      owner, repo, head_sha: pr.head.sha, per_page: 100,
    });
    const requiredPaths = ['.github/workflows/ci.yml', '.github/workflows/sbom.yml'];
    const passed = requiredPaths.every(path => {
      const latest = runs.filter(r => r.path === path &&
        ['pull_request', 'workflow_dispatch'].includes(r.event))
        .sort((a, b) => b.id - a.id)[0];
      return latest?.status === 'completed' && latest.conclusion === 'success';
    });
    if (!passed) {
      core.info(`PR #${pr.number}: waiting for successful CI and SBOM runs.`);
      continue;
    }
    // Check the head and the PR merge revision, including external CI/statuses.
    const current = (await github.rest.pulls.get({owner, repo, pull_number: pr.number})).data;
    if (current.head.sha !== pr.head.sha || current.state !== 'open') continue;
    let blocked = false;
    for (const ref of new Set([pr.head.sha, current.merge_commit_sha].filter(Boolean))) {
      const checks = await github.paginate(github.rest.checks.listForRef, {
        owner, repo, ref, filter: 'latest', per_page: 100,
      });
      if (checks.some(c => c.name !== 'Bot auto-merge' &&
          (c.status !== 'completed' || !['success', 'neutral', 'skipped'].includes(c.conclusion)))) {
        blocked = true;
      }
      const statuses = (await github.rest.repos.getCombinedStatusForRef({owner, repo, ref})).data;
      if (statuses.total_count > 0 && statuses.state !== 'success') blocked = true;
    }
    if (blocked) {
      core.info(`PR #${pr.number}: another check is pending or unsuccessful.`);
      continue;
    }
    // The SHA precondition prevents merging a revision pushed after validation.
    // GitHub still enforces branch protection and review requirements.
    const result = await github.rest.pulls.merge({
      owner, repo, pull_number: pr.number, sha: pr.head.sha, merge_method: 'rebase',
    });
    core.info(`PR #${pr.number}: ${result.data.message}`);
  }
};
