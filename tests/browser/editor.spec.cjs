const {test, expect} = require('@playwright/test');
const path = require('node:path');
const fs = require('node:fs');

const fixture = path.resolve(__dirname, 'fixture.webm');
const PAGES = 'http://127.0.0.1:8877/';
const LOCAL = 'http://127.0.0.1:8878/';

async function openFlatMovie(page) {
  await page.goto(PAGES);
  await page.locator('#fileInput').setInputFiles(fixture);
  await expect(page.locator('#split')).toBeEnabled({timeout: 15000});
  await expect(page.locator('#segmentList > *')).toHaveCount(1);
}
async function seek(page,time) {
  await page.locator('#sourceVideo').evaluate((v,t)=>{
    v.currentTime=t;
    v.dispatchEvent(new Event('timeupdate'));
  },time);
  await expect.poll(()=>page.locator('#sourceVideo')
    .evaluate(v=>v.currentTime)).toBeGreaterThan(.5);
}

test('desktop Pages: split, cut, undo, redo, recovery after reload', async ({page})=>{
  await page.setViewportSize({width:1400,height:900});
  await openFlatMovie(page);
  await seek(page,1);
  await page.locator('#split').click();
  await expect(page.locator('#segmentList > *')).toHaveCount(2);
  await page.locator('#toggleKeep').click();
  await expect(page.locator('#timeline .clip.cut')).toHaveCount(1);
  await page.locator('#editUndo').click();
  await expect(page.locator('#timeline .clip.cut')).toHaveCount(0);
  await page.locator('#editRedo').click();
  await expect(page.locator('#timeline .clip.cut')).toHaveCount(1);

  // The same source file triggers a user-approved localStorage draft restore.
  await page.reload();
  page.once('dialog',d=>d.accept());
  await page.locator('#fileInput').setInputFiles(fixture);
  await expect(page.locator('#segmentList > *')).toHaveCount(2);
  await expect(page.locator('#timeline .clip.cut')).toHaveCount(1);

  // Source media must never be written to localStorage.
  const saved=await page.evaluate(()=>Object.entries(localStorage));
  expect(saved.length).toBeGreaterThan(0);
  expect(saved.every(([key,value])=>!key.includes('blob:')&&!value.includes('data:video/'))).toBeTruthy();
});

test('iPhone-width Pages: editor tool selection and history accessible', async ({page})=>{
  await page.setViewportSize({width:390,height:844});
  await openFlatMovie(page);
  await expect(page.locator('#mobileActions')).toBeVisible();
  await seek(page,1);
  await page.locator('#mobileActions [data-action="split"]').click();
  await expect(page.locator('#segmentList > *')).toHaveCount(2);
  await page.locator('#editUndo').click();
  await expect(page.locator('#segmentList > *')).toHaveCount(1);
  await page.locator('#mobileTabs [data-tab="output"]').click();
  await expect(page.locator('#saveJsonBottom')).toBeVisible();
  await page.locator('#mobileTabs [data-tab="timeline"]').click();
  await expect(page.locator('#timelineViewport')).toBeVisible();
});

test('local native: revision conflict refuses stale browser write', async ({page, request})=>{
  const upload=await request.post(LOCAL+'api/projects',{
    multipart:{
      file:{name:'fixture.mp4',mimeType:'video/webm',buffer:fs.readFileSync(fixture)},
      projection:'flat',
    }
  });
  expect(upload.ok()).toBeTruthy();
  const created=await upload.json(),pid=created.project.id;
  await expect.poll(async()=>{
    const response=await request.get(LOCAL+'api/jobs/'+created.job_id);
    return (await response.json()).state;
  },{timeout:60000}).toBe('done');
  await page.goto(LOCAL);
  await expect(page.locator('.project[data-id="'+pid+'"]')).toBeVisible();
  await page.locator('.project[data-id="'+pid+'"]').click();
  await expect(page.locator('#split')).toBeVisible();
  await page.locator('#player').evaluate(v=>{v.currentTime=1;v.dispatchEvent(new Event('timeupdate'));});
  await page.locator('#split').click();
  await page.locator('#save').click();
  await expect(page.locator('#toast')).toContainText('保存しました');
  const before=(await (await request.get(LOCAL+'api/projects/'+pid)).json()).edit_revision;

  // Another client saves new edits while this tab has an old baseline.
  const other=await request.get(LOCAL+'api/projects/'+pid);
  const remote=await other.json();
  remote.segments[0].keep=false;
  const changed=await request.put(LOCAL+'api/projects/'+pid+'/edits',
    {data:{segments:remote.segments,expected_revision:remote.edit_revision}});
  expect(changed.status()).toBe(200);
  await page.locator('#toggle').click();
  await page.locator('#save').click();
  await expect(page.locator('#editSafety')).toContainText('競合');
  await expect(page.locator('#exportDraft')).toBeVisible();
  const protectedProject=await (await request.get(LOCAL+'api/projects/'+pid)).json();
  expect(protectedProject.edit_revision).toBeGreaterThan(before);
  expect(protectedProject.segments[0].keep).toBe(false);
});
