async (page) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.setDefaultTimeout(15000);
  await page.reload();
  const check = (value, message) => { if (!value) throw new Error(message); };
  const settled = async () => page.waitForFunction(() =>
    document.querySelector('#playbook-board-status').textContent.includes('Diagnóstico atualizado'), null, {timeout: 15000});
  await settled();
  check(await page.locator('[data-slot-id]').count() === 14, '14 initial slots');
  await page.locator('#playbook-board-add-participant').click();
  const option = page.locator('[data-include-member]').first();
  const memberId = await option.getAttribute('data-include-member');
  await option.click();
  await page.locator(`[data-remove-participant="${memberId}"]`).waitFor();
  await settled();
  await page.locator(`[data-remove-participant="${memberId}"]`).click();
  await page.locator(`[data-remove-participant="${memberId}"]`).waitFor({state: 'detached'});
  await page.locator('#playbook-board-add-participant').click();
  await page.locator(`[data-include-member="${memberId}"]`).click();
  await page.locator(`[data-remove-participant="${memberId}"]`).waitFor();
  await settled();
  // Deliberately return a stale preview after the newly selected session.
  await page.evaluate(() => {
    const originalFetch = window.fetch;
    window.fetch = async (...args) => {
      if (!String(args[0]).includes('/composition/preview')) return originalFetch(...args);
      window.fetch = originalFetch;
      const response = await originalFetch(...args);
      return new Promise(resolve => { window.releaseHeldPreview = () => resolve(response); });
    };
  });
  await page.locator('#playbook-board-recalculate').click();
  await page.waitForFunction(() => typeof window.releaseHeldPreview === 'function', null, {timeout: 15000});
  await page.locator('#playbook-board-session').selectOption({label: 'Sessão B de teste'});
  await page.waitForFunction(() => document.querySelector('#playbook-board-participants').textContent.includes('Nenhum participante'), null, {timeout: 15000});
  await page.evaluate(() => { window.releaseHeldPreview(); delete window.releaseHeldPreview; });
  // Browser event loop barrier, then ensure the old session did not reappear.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  check(await page.locator('[data-remove-participant]').count() === 0, 'stale response discarded');
  await page.locator('[data-board-mode="DIRECIONADO"]').click();
  await settled();
  check(await page.locator('[data-board-mode="DIRECIONADO"]').getAttribute('aria-pressed') === 'true', 'mode switch');
  await page.locator('#playbook-board-add-team-block').click();
  await page.waitForFunction(() => document.querySelectorAll('[data-slot-id]').length === 28, null, {timeout: 15000});
  const positions = await page.locator('[data-slot-id]').evaluateAll(slots => slots.map(slot => slot.getAttribute('transform')));
  check(new Set(positions).size === positions.length, 'blocks must not overlap at default positions');
  await page.setViewportSize({width: 390, height: 844});
  await page.locator('#playbook-board-panel').screenshot({path: 'output/playwright/board-mobile.png'});
  check(errors.length === 0, errors.join('; '));
  return {browser: 'WebKit', passed: ['initial preview', 'include', 'exclude', 'reinclude', 'stale response', 'mode', 'add blocks', 'mobile render'], pageErrors: errors};
}
