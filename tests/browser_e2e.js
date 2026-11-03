const { chromium } = require('playwright');
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch();
  const url = 'http://127.0.0.1:8000/';
  const errors = [];
  const open = async (name) => {
    const p = await browser.newPage();
    p.on('pageerror', e => errors.push(`${name}: ${e}`));
    await p.goto(url);
    return p;
  };
  const a = await open('A'), b = await open('B');
  await sleep(10000);
  await b.evaluate(() => window.liverecall.demoDrop());       // B offline 8 s
  await sleep(4000);
  const midStatus = await b.textContent('#status');
  await sleep(9000);
  const c = await open('C (late)');
  await sleep(12000);
  const summary = async (p) => p.evaluate(() => {
    const segs = [...window.liverecall.segments.values()];
    const finals = segs.filter(s => s.final).map(s => s.segment).sort((x, y) => x - y);
    const gaps = [];
    for (let i = 1; i < finals.length; i++) if (finals[i] !== finals[i - 1] + 1) gaps.push([finals[i - 1], finals[i]]);
    const rowSegs = [...document.querySelectorAll('#live .caption .seg')].map(e => e.textContent);
    return { finals: finals.length, first: finals[0], last: finals.at(-1), gaps,
      dupRows: rowSegs.length - new Set(rowSegs).size, stats: window.liverecall.stats,
      status: document.querySelector('#status').textContent };
  });
  console.log('B status while dropped:', midStatus);
  for (const [n, p] of [['A', a], ['B', b], ['C', c]]) console.log(n, JSON.stringify(await summary(p)));
  await a.click('#miss'); await sleep(300);
  console.log('recall 30:', await a.textContent('#recall h2'));
  await a.click('button[data-seconds="60"]:not(#miss)'); await sleep(300);
  console.log('recall 60:', await a.textContent('#recall h2'));
  await a.click('button[data-seconds="15"]'); await sleep(300);
  console.log('recall 15:', await a.textContent('#recall h2'));
  await a.screenshot({ path: 'shot.png', fullPage: true });
  console.log('errors:', errors);
  await browser.close();
})();
