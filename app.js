module.exports = (app) => {
  // Log startup
  app.log.info('Agentic Replenishment app loaded.');

  const AUTOREVIEW_ENABLED = process.env.AUTOREVIEW_ENABLED !== 'false'; // default true
  const MAX_LINES = parseInt(process.env.AUTOREVIEW_MAX_LINES || '50', 10); // max total additions+deletions
  const ALLOWLIST_USERS = (process.env.AUTOREVIEW_ALLOWLIST || '').split(',').map(s => s.trim()).filter(Boolean); // optional author allowlist
  const OPENAI_KEY = process.env.OPENAI_API_KEY || null;

  // Helper: simple heuristic to decide if PR is safe for auto-approve
  async function simpleHeuristic(files) {
    // Count total changed lines
    let totalChanges = 0;
    let nonDocFiles = 0;
    for (const f of files) {
      totalChanges += (f.additions || 0) + (f.deletions || 0);
      const lower = f.filename.toLowerCase();
      // consider docs any markdown, txt, or changes under docs/
      const isDoc = lower.endsWith('.md') || lower.endsWith('.txt') || lower.startsWith('docs/') || lower.includes('/docs/');
      if (!isDoc) nonDocFiles++;
    }
    // Accept if small and only docs or very small code tweak
    return {
      approve: totalChanges <= MAX_LINES && nonDocFiles <= 1,
      totalChanges,
      nonDocFiles
    };
  }

  // Helper: call OpenAI to evaluate diff (optional)
  async function aiEvaluate(diffText, openaiClient) {
    // Keep prompt concise, asking for a binary approval recommendation and a short justification
    const system = "You are an automated code-review assistant. Given a pull request diff, decide if it is safe to auto-approve. Answer with JSON:{\"approve\": true|false, \"confidence\": 0-1, \"reason\": \"...\"}.";
    const user = `Diff:\n${diffText}\n\nConsider code quality, obvious bugs, security, and surprising changes. Small doc-only changes should be APPROVED. Provide only valid JSON.`;

    const resp = await openaiClient.chat.completions.create({
      model: 'gpt-4o-mini',
      messages: [
        { role: 'system', content: system },
        { role: 'user', content: user }
      ],
      max_tokens: 200
    });

    const text = resp.choices?.[0]?.message?.content || resp.choices?.[0]?.text || '';
    try {
      // Attempt to parse JSON out of model output
      const jsonStart = text.indexOf('{');
      const json = JSON.parse(text.slice(jsonStart));
      return json;
    } catch (e) {
      return { approve: false, confidence: 0, reason: 'AI response malformed or not trusted.' };
    }
  }

  // Main: evaluate PR and create APPROVE review if criteria met
  async function evaluateAndMaybeApprove(context) {
    if (!AUTOREVIEW_ENABLED) {
      app.log.info('Auto-review disabled via AUTOREVIEW_ENABLED=false');
      return;
    }

    const owner = context.payload.repository.owner.login;
    const repo = context.payload.repository.name;
    const pull_number = context.payload.pull_request.number;
    const author = context.payload.pull_request.user.login;

    if (ALLOWLIST_USERS.length > 0 && !ALLOWLIST_USERS.includes(author)) {
      app.log.info(`PR author ${author} not in allowlist; skipping auto-approve`);
      return;
    }

    // Fetch files in the PR
    const filesResp = await context.octokit.pulls.listFiles({
      owner, repo, pull_number, per_page: 250
    });
    const files = filesResp.data;

    // Simple heuristic first
    const heur = await simpleHeuristic(files);
    app.log.info(`PR #${pull_number} heuristic: totalChanges=${heur.totalChanges} nonDocFiles=${heur.nonDocFiles} approve=${heur.approve}`);

    let shouldApprove = heur.approve;
    let reason = `Heuristic approved: totalChanges=${heur.totalChanges}, nonDocFiles=${heur.nonDocFiles}`;

    // If heuristic is unsure and we have OpenAI key, call the model
    if (!shouldApprove && OPENAI_KEY) {
      try {
        // get PR diff text (use the diff media header)
        const prDiffResp = await context.octokit.request('GET /repos/{owner}/{repo}/pulls/{pull_number}', {
          owner, repo, pull_number, headers: { accept: 'application/vnd.github.v3.diff' }
        });

        const diffText = prDiffResp.data.toString();
        // lazy-load OpenAI SDK
        const OpenAI = require('openai');
        const openai = new OpenAI({ apiKey: OPENAI_KEY });

        const aiResult = await aiEvaluate(diffText, openai);
        app.log.info(`AI evaluation for PR #${pull_number}: ${JSON.stringify(aiResult)}`);
        if (aiResult && aiResult.approve && (aiResult.confidence ?? 0) >= 0.8) {
          shouldApprove = true;
          reason = `AI approved with confidence ${aiResult.confidence}: ${aiResult.reason || ''}`;
        } else {
          reason = `AI did not approve (confidence=${aiResult.confidence || 0}): ${aiResult.reason || ''}`;
        }
      } catch (err) {
        app.log.error({ err }, 'OpenAI evaluation failed; falling back to heuristic');
      }
    }

    if (shouldApprove) {
      // Create an approval review
      const body = `Auto-approval by Agentic Replenishment app. Reason: ${reason}`;
      await context.octokit.pulls.createReview({
        owner, repo, pull_number,
        event: 'APPROVE',
        body
      });
      app.log.info(`Auto-approved PR #${pull_number} (${author})`);
      // Optionally add a label to indicate it was auto-approved
      try {
        await context.octokit.issues.addLabels({
          owner, repo, issue_number: pull_number,
          labels: ['auto-approved']
        });
      } catch (e) {
        // ignore label failures
      }
    } else {
      app.log.info(`PR #${pull_number} not approved by auto-review: ${reason}`);
    }
  }

  // Example: comment on newly opened pull requests and attempt auto-approval
  app.on('pull_request.opened', async (context) => {
    const issueComment = context.issue({ body: 'Thanks for the PR! The Agentic Replenishment App is reviewing this.' });
    await context.octokit.issues.createComment(issueComment);
    app.log.info(`Commented on PR #${context.payload.pull_request.number}`);

    // Try auto-approve (non-blocking)
    try {
      await evaluateAndMaybeApprove(context);
    } catch (err) {
      app.log.error({ err }, 'Auto-approval failed for pull_request.opened');
    }
  });

  // Re-evaluate on updated PRs (pushes to the branch)
  app.on('pull_request.synchronize', async (context) => {
    try {
      await evaluateAndMaybeApprove(context);
    } catch (err) {
      app.log.error({ err }, 'Auto-approval failed for pull_request.synchronize');
    }
  });

  // Example: respond to issues opened
  app.on('issues.opened', async (context) => {
    const body = `Thanks for opening this issue — the maintainers will review it soon.`;
    await context.octokit.issues.createComment(context.issue({ body }));
  });

  // Add other event handlers as needed...
};
