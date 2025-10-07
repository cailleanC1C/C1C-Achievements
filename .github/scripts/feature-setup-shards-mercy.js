// Runs inside actions/github-script (github, context, core available)
const { owner, repo } = context.repo;

// ---- Prefilled content ----
const feature = {
  title: 'Achievements - Shards & Mercy (v1)',
  bot: 'bot:achievements',
  comp: 'comp:shards',
  summary:
    "Add a clan-aware Shards & Mercy module to Achievements: users drop a shard-count screenshot in their clan's shard thread; the bot OCRs counts (with manual fallback), stores inventory and events in Sheets, tracks mercy per shard type, and keeps a pinned weekly summary message per clan.",
  problem:
    'Leads and recruiters lack a reliable, up-to-date shard inventory and pity ledger; screenshots are scattered and mercy math is error-prone. We want a fast, thread-native flow that produces a trustworthy ledger and a clean weekly summary.',
  useCases: [
    'Player posts screenshot -> bot reads five shard counts -> user confirms -> snapshot saved',
    'Track mercy per user per shard type; reset correctly on Legendary (incl. Guaranteed/Extra rules)',
    'Users/staff can set initial mercy or reset manually; never block UX if OCR fails',
    'Keep exactly one pinned summary per clan; update within ISO week; new message on week rollover',
    'All actions live in clan shard threads; permissions tied to clan roles'
  ],
  subtasks: [
    'Guards & config',
    'Sheets adapters',
    'Watcher (OCR/manual)',
    'Commands & UI',
    'Mercy engine & ledger',
    'Summary renderer (weekly pinned)',
    'Concurrency & rate limits',
    'Validation & staff tools'
  ],
  acceptance: [
    'Posting an image in a clan shard thread offers Scan Image; preview shows five counts; Confirm writes a snapshot row with timestamp and message link',
    'If OCR cannot read confidently, Manual entry saves counts; UX never blocks',
    'mercy addpulls records batch with shard type/qty/flags; Legendary pulls reset correct mercy counters; Guaranteed/Extra Legendary follow rules',
    'Users/staff can set initial mercy or reset via command; changes persist',
    'Exactly one pinned This Week summary per clan; edits within week update it; new week creates a new message',
    'Summary shows totals, paged member list (stable sort by name then ID), last updated time',
    'Actions limited to configured shard threads; clan role checks; staff override works',
    'Sheets writes are idempotent/retried; no double-writes on rapid updates'
  ]
};
// ---------------------------

const epicTitle = `[Feature] ${feature.title}`;

// Idempotency: skip if epic already exists
const search = await github.rest.search.issuesAndPullRequests({
  q: `repo:${owner}/${repo} is:issue in:title "${epicTitle}"`
});
if (search.data.total_count > 0) {
  const existing = search.data.items[0];
  core.notice(`Epic already exists (#${existing.number}). Skipping creation.`);
  return;
}

const labelsEpic = ['feature', feature.bot, feature.comp];

const bullets = feature.useCases.map(u => `- ${u}`).join('\n');
const plan    = feature.subtasks.map(s => `- [ ] ${s}`).join('\n');
const acc     = feature.acceptance.map(a => `- [ ] ${a}`).join('\n');

const epicBody = [
  '### Summary',
  feature.summary,
  '',
  '### Problem / goal',
  feature.problem,
  '',
  '### Core use cases (v1)',
  bullets,
  '',
  '### High-level design (agreed)',
  `- Module: ${feature.bot} / ${feature.comp}`,
  '- Data: snapshots (inventory) + events (pull ledger)',
  '- Commands/UI: modal/commands; weekly summary rules',
  '- Guards/ops: thread-only, role gating, retries/backoff',
  '',
  '### Implementation plan (v1 steps)',
  plan,
  '',
  '### Acceptance criteria (testable)',
  acc,
  '',
  '### Rollout',
  'Dry-run in 1-2 clans; staff override; fallback = manual entry only.'
].join('\n');

// Create Epic
const epic = await github.rest.issues.create({
  owner, repo, title: epicTitle, labels: labelsEpic, body: epicBody
});
const epicNum = epic.data.number;

// Sub-issues (Watcher -> comp:ocr; others -> comp:shards)
const linkLines = [];
for (const s of feature.subtasks) {
  const isWatcher = /watcher|ocr/i.test(s);
  const compForSub = isWatcher ? 'comp:ocr' : feature.comp;
  const sub = await github.rest.issues.create({
    owner, repo,
    title: `[Feature] ${s} - ${feature.title}`,
    labels: ['feature', feature.bot, compForSub],
    body: `Split from #${epicNum}`
  });
  linkLines.push(`- [ ] ${s} (#${sub.data.number})`);
}

// Append checklist to Epic
await github.rest.issues.update({
  owner, repo, issue_number: epicNum,
  body: `${epic.data.body}\n\n### Sub-issues\n${linkLines.join('\n')}`
});

core.summary
  .addHeading('Feature setup created')
  .addRaw(`Epic: #${epicNum}\n\n${linkLines.join('\n')}`)
  .write();
