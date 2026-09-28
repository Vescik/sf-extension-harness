/** Bounded teardown: discard pipes immediately, then force a stubborn child to exit. */
export function terminateProcess(child) {
  child.stdin?.destroy();
  child.stdout?.destroy();
  child.stderr?.destroy();
  if (child.exitCode !== null || child.signalCode) return;
  child.kill('SIGTERM');
  const force = setTimeout(() => {
    if (child.exitCode === null && !child.signalCode) child.kill('SIGKILL');
  }, 250);
  force.unref();
  child.once('close', () => clearTimeout(force));
}
