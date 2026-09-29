const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const event = () => ({addListener(fn) { this.listener = fn; }});
function harness(nativeReply = {status:'ok'}) {
  const local = {}, session = {}, sent = [], actions = [];
  function store(data) { return {
    async get(keys) { return Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(k => [k, data[k]])); },
    async set(value) { Object.assign(data, value); },
    async remove(key) { delete data[key]; }
  }; }
  const chrome = {
    runtime: {onInstalled:event(), onMessage:event(), async sendNativeMessage(host, message) {sent.push(message); return nativeReply;}},
    contextMenus: {onClicked:event(),removeAll(cb){cb();},create(){}},
    storage:{local:store(local),session:store(session)},
    action:{async setBadgeText(){},async setBadgeBackgroundColor(){}},
    webRequest:{onHeadersReceived:event()},tabs:{onRemoved:event()},
    downloads:{onCreated:event(), async pause(id){actions.push('pause');},async cancel(id){actions.push('cancel');},async resume(id){actions.push('resume');}}
  };
  vm.runInNewContext(fs.readFileSync('browser/extension/background.js','utf8'), {chrome, console, URL, navigator:{userAgent:'Test Browser'}});
  const message = (body, sender={}) => new Promise(resolve => chrome.runtime.onMessage.listener(body,sender,resolve));
  return {chrome,local,session,sent,actions,message};
}
test('download forwards real URL and frame referrer with actual acknowledgement', async () => {
  const h=harness();
  const response=await h.message({action:'download',url:'https://cdn.example/video.mp4'}, {url:'https://example/page'});
  assert.equal(response.status,'ok');
  assert.equal(h.sent[0].url,'https://cdn.example/video.mp4');
  assert.equal(h.sent[0].headers.Referer,'https://example/page');
});
test('native errors reach content script and popup',async()=>{
  const h=harness({status:'error',message:'App unavailable'});
  const response=await h.message({action:'download',url:'https://example/file.zip'});
  assert.equal(response.status,'error');
  assert.match(h.local.lastError,/App unavailable/);
});
test('browser-only blob URLs are rejected rather than downloaded as pages',async()=>{
  const h=harness();
  assert.equal((await h.message({action:'download',url:'blob:123'})).status,'error');
  assert.equal(h.sent.length,0);
});
test('browser capture is opt-in and cancels only after acceptance',async()=>{
  const h=harness();
  const item={id:1,url:'https://example/file.zip'};
  await h.chrome.downloads.onCreated.listener(item);
  assert.equal(h.sent.length,0);
  h.local.captureDownloads=true;
  await h.chrome.downloads.onCreated.listener(item);
  assert.deepEqual(h.actions,['pause','cancel']);
});
test('failed handoff resumes browser download',async()=>{
  const h=harness({status:'error',message:'Unavailable'});
  h.local.captureDownloads=true;
  await h.chrome.downloads.onCreated.listener({id:2,url:'https://example/file.zip'});
  assert.deepEqual(h.actions,['pause','resume']);
});
test('network discovery ignores fragments and isolates frames and navigations',async()=>{
  const h=harness();
  const event=(url,frameId=0,type='xmlhttprequest')=>h.chrome.webRequest.onHeadersReceived.listener({tabId:1,frameId,type,url,statusCode:200,responseHeaders:[{name:'Content-Type',value:'video/mp4'}]});
  event('https://example/movie.mp4');
  event('https://example/chunk.m4s');
  event('https://example/embedded.mp4',4);
  let result=await h.message({action:'media'}, {tab:{id:1},frameId:0});
  assert.equal(result.media.length,1);
  assert.equal(result.media[0].url,'https://example/movie.mp4');
  event('https://example/new',0,'main_frame');
  result=await h.message({action:'media',tabId:1});
  assert.equal(result.media.length,0);
});
