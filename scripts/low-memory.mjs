// Supervise only this command's descendants; never stop the user's applications.
import { spawn, execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
const args = process.argv.slice(2);
if (!args.length) throw new Error('Usage: node scripts/low-memory.mjs command [args]');
const child = spawn(args[0], args.slice(1), {
  stdio: 'inherit', detached: process.platform !== 'win32',
  env: { ...process.env, UV_THREADPOOL_SIZE: '1', NEXT_TELEMETRY_DISABLED: '1', OMP_NUM_THREADS: '1', NODE_OPTIONS: '--max-old-space-size=1024' },
});
let peakKb = 0;
let stopped = false;
const stop = () => {
  if (stopped) return;
  stopped = true;
  try { process.kill(process.platform === 'win32' ? child.pid : -child.pid, 'SIGTERM'); } catch {}
  setTimeout(() => { try { process.kill(-child.pid, 'SIGKILL'); } catch {} }, 3000).unref();
};
const timer = setInterval(() => {
  if (process.platform !== 'linux') return;
  try {
    const rows = execFileSync('ps', ['-eo', 'pid=,ppid=,rss='], { encoding: 'utf8' }).trim().split('\n').map(l => l.trim().split(/\s+/).map(Number));
    const descendants = new Set([child.pid]);
    for (let n = 0; n < 20; n++) for (const [pid, ppid] of rows) if (descendants.has(ppid)) descendants.add(pid);
    const rss = rows.reduce((sum, [pid, , kb]) => sum + (descendants.has(pid) ? kb : 0), 0);
    peakKb = Math.max(peakKb, rss);
    const available = Number(readFileSync('/proc/meminfo', 'utf8').match(/MemAvailable:\s+(\d+)/)?.[1]);
    if (rss > 1536 * 1024 || (available > 0 && available < 256 * 1024)) {
      console.error('\nMemory guard stopped this task to keep the laptop responsive. Run this check in CI or close unused applications.');
      stop();
    }
  } catch { /* Memory sampling unavailable; per-process heap limit still applies. */ }
}, 1000);
child.on('error', e => { clearInterval(timer); console.error(e.message); process.exitCode = 1; });
child.on('exit', code => {
  clearInterval(timer);
  console.log(`Peak sampled task RSS: ${Math.round(peakKb / 1024)} MiB.`);
  process.exitCode = stopped ? 137 : (code ?? 1);
});
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
