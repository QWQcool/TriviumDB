#!/usr/bin/env node
// Run after `bun scripts/v4-preview.mjs`. Requires the existing Playwright test environment.
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync,readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const output=path.join(root,'.tmp','v4-preview');
const base=new URL(process.env.TDB_V4_BASE || 'http://127.0.0.1:8894');
const source=readFileSync(path.join(root,'docs/design/webui-html-drafts/v4-workspace-unification.html'),'utf8');
for(const m of source.matchAll(/<script>([\s\S]*?)<\/script>/g)) new Function(m[1]);
mkdirSync(output,{recursive:true});
const browser=await chromium.launch(); const evidence=[];
const luminance=rgb=>{const c=rgb.map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4});return c[0]*.2126+c[1]*.7152+c[2]*.0722};
const rgb=x=>x.startsWith('#')?x.slice(1).match(/../g).map(x=>parseInt(x,16)):x.match(/[\d.]+/g).slice(0,3).map(Number);
const contrast=(a,b)=>{const x=luminance(rgb(a)),y=luminance(rgb(b));return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)};
try{
 for(const width of [1440,1024,390]){
  const p=await browser.newPage({viewport:{width,height:1100},reducedMotion:'reduce'});const errors=[];const requests=[];
  p.on('pageerror',e=>errors.push(e.message));p.on('console',m=>{if(m.type()==='error')errors.push(m.text())});p.on('request',r=>requests.push(r.url()));
  await p.goto(new URL('/v4',base).href);
  for(const theme of ['dark','light']){
   await p.selectOption('#themeSelect',theme);
   for(const language of ['zh','en']){
    await p.selectOption('#languageSelect',language);
    for(const view of ['query','vector']){
     await p.click('#'+view+'Tab');
     for(const state of ['empty','loading','success','zero','error']){
      await p.selectOption('#stateSelect',state);
      const sizes=await p.evaluate(()=>({scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth}));
      assert(sizes.scroll<=sizes.client,JSON.stringify({width,theme,language,view,state,...sizes}));
      assert(await p.locator('#'+view+'View').isVisible());
     }
     await p.selectOption('#stateSelect','empty');
     if(language==='zh'&&(width===1440||(width===390&&theme==='dark'))){
       await p.locator('.app').screenshot({path:path.join(output,`${view}-${theme}-${width}.png`)});
     }
    }
   }
   const colors=await p.evaluate(()=>{const s=getComputedStyle(document.documentElement);return Object.fromEntries(['text','muted','panel','raised','inset','accent','on-accent','control-border','bad','danger-bg'].map(k=>[k,s.getPropertyValue('--'+k).trim()]))});
   const checks={body:contrast(colors.text,colors.panel),secondary:Math.min(...['panel','raised','inset'].map(k=>contrast(colors.muted,colors[k]))),action:contrast(colors['on-accent'],colors.accent),input:contrast(colors['control-border'],colors.inset),error:contrast(colors.bad,colors['danger-bg'])};
   for(const [k,v] of Object.entries(checks))assert(v>=(k==='input'?3:4.5),`${theme} ${k} contrast=${v}`);
   evidence.push({width,theme,states:20,contrast:checks});
   assert.equal(await p.locator('#nodeSelect').evaluate(el=>getComputedStyle(el).colorScheme),theme);
  }
  await p.selectOption('#languageSelect','zh'); await p.selectOption('#themeSelect','dark');await p.selectOption('#stateSelect','empty');
  await p.click('#queryTab');await p.click('#queryRun');await p.waitForSelector('#queryResult tr[data-node]');await p.locator('#queryResult tr[data-node]').first().click();assert(await p.locator('#queryInspector').isVisible());await p.keyboard.press('Escape');assert(!(await p.locator('#queryInspector').isVisible()));
  await p.click('[data-result="json"]');assert((await p.locator('#queryResult').innerText()).includes('Alice'));await p.click('[data-result="table"]');
  await p.click('#vectorTab');await p.click('#loadCandidates');await p.selectOption('#nodeSelect','Bob');assert((await p.locator('#vectorValue').innerText()).includes('Bob'));await p.click('#vectorRun');await p.waitForSelector('#vectorResult tr[data-node]');
  if(width===1440)await p.locator('.app').screenshot({path:path.join(output,'vector-dark-results.png')});
  await p.click('#jsonSource');assert(await p.locator('#jsonVector').isVisible());await p.click('#expandVector');assert((await p.locator('#vectorValue').innerText()).includes('0.33'));
  await p.click('#beforeBtn');assert.equal(await p.locator('html').getAttribute('data-version'),'before');await p.click('#v4Btn');
  assert.deepEqual(errors,[]);assert(requests.every(url=>new URL(url).origin===base.origin),'No external requests');
  console.log(`PASS ${width}: dark/light × zh/en × TQL/vector × 5 states; interactions; zero errors`);await p.close();
 }
 writeFileSync(path.join(output,'checks.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify(evidence.filter(x=>x.width===1440),null,2));
}finally{await browser.close()}
