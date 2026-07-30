import { chromium } from 'playwright';
const r = await fetch('http://localhost:5050/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({role:'admin',pin:'ept-admin-2026'})});
const tok = (await r.json()).token;
const b = await chromium.launch();
for (const [lbl, w] of [['mobil 390',390],['desktop 1440',1440]]) {
  const c = await b.newContext({viewport:{width:w,height:900}});
  const p = await c.newPage();
  await p.addInitScript(t=>{sessionStorage.setItem('ept_token',t);sessionStorage.setItem('ept_role','admin');localStorage.setItem('ept_theme','dark');},tok);
  await p.goto('http://localhost:5050/',{waitUntil:'networkidle'});
  const g = await p.evaluate(() => {
    const box = s => { const e=document.querySelector(s); const r=e.getBoundingClientRect(); return {t:r.top,b:r.bottom,h:r.height}; };
    const lab = n => [...document.querySelectorAll('label.lbl')].find(l=>l.textContent.trim()===n).getBoundingClientRect();
    return {
      jmeno: box('#fJmeno'), prijmeni: box('#fPrijmeni'), org: box('#fOrg'), spz: box('#fSpz'),
      lPrijmeni: lab('Příjmení').top, lOrg: lab('Organizace').top, lSpz: lab('SPZ vozidla').top,
    };
  });
  console.log(`\n${lbl}:`);
  console.log(`  výška pole:                 ${g.jmeno.h.toFixed(1)} px  (cíl >= 44 na mobilu)`);
  console.log(`  Jan   -> popisek PŘÍJMENÍ:  ${(g.lPrijmeni - g.jmeno.b).toFixed(1)} px`);
  console.log(`  Novák -> popisek ORGANIZACE:${(g.lOrg - g.prijmeni.b).toFixed(1)} px`);
  console.log(`  Firma -> popisek SPZ:       ${(g.lSpz - g.org.b).toFixed(1)} px`);
  await c.close();
}
await b.close();
