/* Browser interaction regression. ONLY run against a disposable project: edits are
 * deliberately synthetic QA coordinates, not real human keypoint annotations. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.argv[2]||'http://127.0.0.1:8766';
const output=process.argv[3]||'local/keypoint_review/browser_qa';
fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROME_BIN||'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1600,height:1100},deviceScaleFactor:2,acceptDownloads:true});
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base);await page.waitForSelector('.point');
 const read=()=>page.evaluate(async()=> (await(await fetch('/api/document')).json()).document);
 const save=async()=>{await page.locator('#save').click();await page.waitForFunction(()=>document.getElementById('saveState').textContent.startsWith('已保存'));};
 const locate=async(x,y)=>{await page.locator('#canvas').scrollIntoViewIfNeeded();return page.locator('#canvas').evaluate((e,[x,y])=>{const r=e.getBoundingClientRect();return {x:r.x+(x+.5)*r.width/128,y:r.y+(y+.5)*r.height/128};},[x,y]);};
 const click=async(x,y)=>{const p=await locate(x,y);await page.mouse.click(p.x,p.y);};
 const verify=async(i,x,y)=>{assert(Math.abs(Number(await page.getByLabel(names[i]+' x',{exact:true}).inputValue())-x)<.05);assert(Math.abs(Number(await page.getByLabel(names[i]+' y',{exact:true}).inputValue())-y)<.05);};
 const names=['plug_tip_left','plug_tip_right','socket_top_left','socket_top_right','socket_bottom_left','socket_bottom_right'];
 assert.equal(await page.locator('.imageItem').count(),12);assert.equal(await page.locator('.point').count(),6);
 await page.locator('#batch').click();await page.waitForFunction(()=>document.getElementById('saveState').textContent.startsWith('候选已保存'));
 assert((await read()).images.every(r=>r.proposals.length));
 // DPR2, default zoom4, original pixel-center convention.
 await click(40,45);await verify(0,40,45);
 // Drag with pointer capture.
 let a=await locate(40,45),b=await locate(42.5,48.25);await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(b.x,b.y,{steps:5});await page.mouse.up();await verify(0,42.5,48.25);
 await page.locator('#undo').click();await verify(0,40,45);await page.locator('#redo').click();await verify(0,42.5,48.25);
 await page.locator('#zoom').fill('8');await page.locator('#viewport').evaluate(e=>{e.scrollLeft=180;e.scrollTop=230;});
 // Recompute client position after scroll; do not use canvas pixel coordinates as screen values.
 await click(60,60);await verify(0,60,60);
 await page.locator('#interpolation').selectOption('auto');await save();await page.reload();await page.waitForSelector('.point');await verify(0,60,60);
 // Geometry and target draft saved independently; these synthetic positions test schema only.
 const coords=[[40,70],[55,70],[40,25],[55,25],[40,45],[55,45]];
 for(let i=0;i<6;i++){await page.locator('.point .name').nth(i).click();await click(...coords[i]);}
 await page.getByLabel(names[1]+' 状态',{exact:true}).selectOption('occluded');
 await page.getByLabel(names[5]+' 状态',{exact:true}).selectOption('uncertain');
 // Declare reference regions by actual pointer drags.
 async function roi(button,x0,y0,x1,y1){await page.locator(button).click();await page.locator('#viewport').scrollIntoViewIfNeeded();let a=await locate(x0,y0),b=await locate(x1,y1);await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(b.x,b.y,{steps:4});await page.mouse.up();}
 await roi('#socketRoi',30,15,70,55);await roi('#plugRoi',30,60,70,85);
 await page.locator('#targetId').fill('QA-ONLY-NOT-GROUND-TRUTH');await page.locator('#definition').fill('Synthetic UI test positions. Do not export these as robot training truth.');await page.locator('#definitionConfirmed').check();await page.locator('#anchor').click();await page.waitForFunction(()=>document.getElementById('saveState').textContent.startsWith('已保存'));
 await page.locator('#review').click();await page.waitForFunction(()=>document.getElementById('reviewState').textContent.includes('整图已审核'));
 let doc=await read();assert.equal(doc.images[0].review_status,'reviewed');assert.equal(doc.images[0].keypoints[1].x,null);assert.equal(doc.images[0].keypoints[5].x,null);
 const labels=JSON.stringify(doc.images[0].keypoints);
 await page.locator('#predict').click();await page.waitForFunction(()=>document.getElementById('saveState').textContent.startsWith('候选已保存'));
 assert.equal(JSON.stringify((await read()).images[0].keypoints),labels);assert.equal((await read()).images[0].review_status,'reviewed');
 const downloadPromise=page.waitForEvent('download');await page.locator('#training').click();const download=await downloadPromise;await download.saveAs(output+'/qa-only-export.npz');
 // Point edits invalidate image approval; navigation saves before changing view.
 await page.locator('.point .name').first().click();await click(41,70);await page.locator('#next').click();await page.waitForFunction(()=>document.getElementById('imageTitle').textContent.includes('wrist'));
 doc=await read();assert.equal(doc.images[0].review_status,'unreviewed');assert(Math.abs(doc.images[0].keypoints[0].x-41)<.05);
 // Same-file multi-window revision conflicts retain the local edit.
 const other=await context.newPage();await other.goto(base);await other.waitForSelector('.point');
 await page.locator('.point .name').first().click();await click(30,30);await save();
 const otherCanvas=await other.locator('#canvas').boundingBox();await other.mouse.click(otherCanvas.x+82,otherCanvas.y+102);await other.locator('#save').click();await other.waitForFunction(()=>document.getElementById('saveState').textContent.includes('保存失败'));
 assert.equal(await other.getByLabel(names[0]+' x',{exact:true}).inputValue(),'20');
 other.on('dialog',d=>d.accept());await other.close();
 // HTTP save failure cannot discard current edits or navigate away.
 await click(31,32);await page.route('**/api/save',route=>route.fulfill({status:507,contentType:'application/json',body:JSON.stringify({error:'injected disk-full test'})}));await page.locator('#next').click();await page.waitForFunction(()=>document.getElementById('saveState').textContent.includes('保存失败'));assert((await page.locator('#imageTitle').textContent()).includes('wrist'));await verify(0,31,32);await page.unroute('**/api/save');await save();
 await page.screenshot({path:output+'/interaction.png',fullPage:true});
 assert.deepEqual(errors,[]);
 fs.writeFileSync(output+'/ui-report.json',JSON.stringify({passed:true,devicePixelRatio:2,images:12,tests:['browse','batch predict','click','drag','undo redo','zoom scroll original coordinates','bilinear','save reload','reference region','review nonvisible','prediction preserves truth','NPZ download','navigation saves','approval invalidation','multi-window conflict retains edit','save failure retains edit'],note:'Synthetic QA positions only. Not robot annotations.'},null,2));
 console.log('UI regression passed');await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
