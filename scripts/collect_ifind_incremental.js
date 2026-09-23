'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

function parseArgs(argv) {
  const result = {};
  for (let i = 2; i < argv.length; i += 2) result[argv[i].replace(/^--/, '')] = argv[i + 1];
  return result;
}

function hasTableRows(answer) {
  const lines = String(answer || '').split(String.fromCharCode(10)).filter((line) => line.trim().startsWith('|'));
  return lines.length >= 3 && !/查询结果为空/.test(String(answer || ''));
}

function answerOf(result) {
  return (result?.data?.result?.content || []).map((item) => {
    try {
      const outer = JSON.parse(item.text || '{}');
      const inner = typeof outer.data === 'string' ? JSON.parse(outer.data) : outer.data;
      return inner?.answer || item.text || '';
    } catch (_) {
      return item.text || '';
    }
  }).join('\n');
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isRateLimited(answer) {
  return /(?:status:\s*429|请求过于频繁|稍后重试)/i.test(String(answer || ''));
}

function isQuotaExhausted(answer) {
  return /(?:用户使用工具已超限|额度已用完|额度不足|额度.*耗尽|quota exhausted|insufficient quota|IFIND_QUOTA_EXHAUSTED)/i.test(String(answer || ''));
}

async function main() {
  const args = parseArgs(process.argv);
  if (!args.jobs || !args.output) throw new Error('Required: --jobs and --output');
  const concurrency = Math.max(1, Math.min(2, Number(args.concurrency || 2)));
  const tool = args.tool || 'get_fund_market_performance';
  const maxAttempts = Math.max(1, Math.min(5, Number(args.attempts || 5)));
  const skillDir = process.env.IFIND_SKILL_DIR || path.join(os.homedir(), '.codex', 'skills', 'ifind-finance-data');
  const { call } = require(path.join(skillDir, 'call-node.js'));
  const jobs = JSON.parse(fs.readFileSync(path.resolve(args.jobs), 'utf8'));
  const output = path.resolve(args.output);
  fs.mkdirSync(path.dirname(output), { recursive: true });
  const completed = new Set();
  if (fs.existsSync(output)) {
    for (const line of fs.readFileSync(output, 'utf8').split(/\r?\n/)) {
      if (!line.trim()) continue;
      try {
        const prior = JSON.parse(line);
        if (prior.status === 'success' && hasTableRows(prior.answer)) completed.add(prior.job_id);
      } catch (_) {}
    }
  }
  const queue = jobs.filter((job) => !completed.has(job.job_id));
  let next = 0;
  let done = completed.size;
  async function worker(workerId) {
    while (true) {
      const index = next++;
      if (index >= queue.length) return;
      const job = queue[index];
      const startedAt = new Date().toISOString();
      let record;
      for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
        try {
          const result = await call('fund', tool, { query: job.query });
          if (isQuotaExhausted(JSON.stringify(result))) {
            const error = new Error('IFIND_QUOTA_EXHAUSTED');
            error.code = 'IFIND_QUOTA_EXHAUSTED';
            throw error;
          }
          const answer = answerOf(result);
          const status = hasTableRows(answer) ? 'success' : 'empty';
          record = { ...job, tool, attempt, answer, result, started_at: startedAt, finished_at: new Date().toISOString(), status };
          if (status === 'success') break;
          if (isQuotaExhausted(answer)) {
            const error = new Error(`iFinD quota exhausted while processing ${job.job_id}: ${answer.slice(0, 300)}`);
            error.code = 'IFIND_QUOTA_EXHAUSTED';
            throw error;
          }
          if (isRateLimited(answer) && attempt < maxAttempts) {
            const delayMs = Math.min(60000, 5000 * (2 ** (attempt - 1)));
            console.error(JSON.stringify({ worker: workerId, job_id: job.job_id, rate_limited: true, retry_in_seconds: delayMs / 1000 }));
            await wait(delayMs);
          }
        } catch (error) {
          if (error?.code === 'IFIND_QUOTA_EXHAUSTED' || isQuotaExhausted(error?.message || error)) throw error;
          record = { ...job, tool, attempt, error: String(error?.stack || error), started_at: startedAt, finished_at: new Date().toISOString(), status: 'error' };
          if (attempt < maxAttempts) await wait(Math.min(30000, 3000 * (2 ** (attempt - 1))));
        }
      }
      fs.appendFileSync(output, JSON.stringify(record) + '\n', 'utf8');
      if (record.status !== 'success') throw new Error(`IFIND_JOB_FAILED: ${job.job_id}`);
      done += 1;
      if (done % 10 === 0 || done === jobs.length) console.log(JSON.stringify({ worker: workerId, done, total: jobs.length }));
      await wait(500);
    }
  }
  await Promise.all(Array.from({ length: concurrency }, (_, i) => worker(i + 1)));
  console.log(JSON.stringify({ done, total: jobs.length, tool, output }));
}

main().catch((error) => { console.error(error); process.exit(1); });
