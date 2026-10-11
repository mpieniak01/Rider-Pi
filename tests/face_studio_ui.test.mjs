// In-memory DOM and REST: no browser hardware, SPI, UART or motor endpoint.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../web/assets/face-studio.js',import.meta.url),'utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function fixture() {
  class Element {
    constructor(){this.value='';this.checked=false;this.disabled=false;this.style={};this.children=[];this.dataset={};}
    add(item){this.children.push(item);if(!this.value)this.value=item.value;}
    append(...items){this.children.push(...items);}
    replaceChildren(...items){this.children=items;this.value='';}
    setAttribute(key,value){this[key]=value;}
    removeAttribute(key){delete this[key];}
    addEventListener(event,fn){this['on'+event]=fn;}
    click(){this.onclick?.();}
    get valueAsNumber(){return Number(this.value);}
  }
  const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  for(const [id,value] of Object.entries({source:'draft',zoom:'240'}))get(id).value=value;
  const events={},jobs=new Map(),calls=[];let id=0,revision='first',pending=null,hold=false;
  const fields={'eyes.dx':[-1,1],'mouth.open':[0,1],'mouth.curve':[-1,1]};
  let settings={style:'friendly',skin:'none',power_mode:'battery',idle:true,intensity:1,tempo:1,transition:'original',active_gestures:['builtin:happy']};
  const descriptors={contract_version:1,styles:[{id:'friendly',pl:'Przyjazna',en:'Friendly'},{id:'minimal',pl:'Prosta',en:'Simple'}],
    skins:[{id:'none',pl:'Bez oprawy',en:'No character'},{id:'human',pl:'Piegusek',en:'Freckles'},{id:'cat',pl:'Kotek',en:'Kitten'},{id:'robot',pl:'Robocik',en:'Little robot'},{id:'professional',pl:'Profesjonalna',en:'Professional'}],
    expressions:['neutral','happy'],expression_defaults:{neutral:{'mouth.curve':.15},happy:{'mouth.curve':.8}},
    intensity:{min:0,max:100,step:1},tempo:{min:50,max:200,step:5},duration:{max:10000,step:10},transitions:['original','lin','in_out'],fps:{preview:12}};
  const gesture={id:'builtin:happy',builtin:true,name:'happy',expr:'happy',duration:1,initial:{'mouth.curve':.8},tracks:{}};
  const response=data=>({ok:true,status:200,json:async()=>data,blob:async()=>new Blob(['PNG']),headers:{get:()=>null}});
  const document={hidden:false,documentElement:{lang:'pl'},getElementById:get,createElement:()=>new Element(),querySelectorAll:()=>[],addEventListener:(event,fn)=>events[event]=fn};
  const fetch=async(url,options={})=>{
    calls.push({url,options});
    if(url.endsWith('/gestures'))return response({gestures:[gesture],fields,descriptors,settings,settings_revision:revision});
    if(url.endsWith('/runtime')){
      if(options.method==='POST'){const body=JSON.parse(options.body);assert.equal(body.if_revision,revision);delete body.if_revision;settings={...settings,...body};revision='saved';}
      return response({state:{running:false},settings,settings_revision:revision});
    }
    if(url.endsWith('/frame')){
      if(hold)return new Promise((resolve,reject)=>{pending=resolve;options.signal?.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'})));});
      return response({});
    }
    throw Error('Unexpected endpoint '+url);
  };
  const context={document,window:{addEventListener:(event,fn)=>events[event]=fn},fetch,Option:function(text,value){this.text=text;this.value=value;},
    setTimeout:(fn,ms)=>{jobs.set(++id,{fn,ms});return id;},clearTimeout:key=>jobs.delete(key),URL:{createObjectURL:()=> 'blob:fixture',revokeObjectURL(){}},
    Blob,AbortController,performance:{now:()=>1000},confirm:()=>true,console};
  vm.runInNewContext(source,context);
  return {get,document,events,jobs,calls,async ready(){await flush();},
    async frame(){const row=[...jobs].find(([,v])=>v.ms===0);assert.ok(row);jobs.delete(row[0]);row[1].fn();await flush();},
    hold(){hold=true;},finish(){pending?.(response({}));},external(value){settings={...settings,...value};revision='external';}};
}
test('descriptor units, saving and visual preview never call LCD or motors',async()=>{
  const f=fixture();await f.ready();await f.frame();
  assert.equal(f.get('tempo').min,50);assert.equal(f.get('intensity').max,100);
  f.get('style').value='minimal';f.get('style').onchange();
  assert.equal(f.get('lcd-play').disabled,true);
  await f.get('apply').onclick();
  assert.equal(f.get('lcd-play').disabled,false);
  const saved=JSON.parse(f.calls.find(x=>x.url.endsWith('/runtime')&&x.options.method==='POST').options.body);
  assert.equal(saved.style,'minimal');assert.equal(saved.intensity,1);
  assert.ok(f.calls.every(x=>!x.url.includes('/play')&&!x.url.includes('/motion')));
});
test('hidden tabs abort frame and remove preview/state timers',async()=>{
  const f=fixture();await f.ready();f.hold();await f.frame();
  assert.ok(f.calls.at(-1).options.signal);
  f.document.hidden=true;f.events.visibilitychange();await flush();
  assert.equal(f.calls.at(-1).options.signal.aborted,true);
  assert.equal(f.jobs.size,0);
});
test('at most one frame request is in flight during repeated slider changes',async()=>{
  const f=fixture();await f.ready();f.hold();await f.frame();
  const count=f.calls.filter(x=>x.url.endsWith('/frame')).length;
  for(let i=0;i<5;i++){f.get('scrub').value=50+i;f.get('scrub').oninput();}
  await f.frame();await f.frame();
  assert.equal(f.calls.filter(x=>x.url.endsWith('/frame')).length,count+1);
  f.document.hidden=true;f.events.visibilitychange();await flush();
});
test('reload fetches current shared settings without activating the face',async()=>{
  const f=fixture();await f.ready();f.external({style:'minimal',tempo:.5});
  await f.get('reload-settings').onclick();
  assert.equal(f.get('style').value,'minimal');assert.equal(f.get('tempo').value,50);
  assert.ok(f.calls.every(x=>!x.url.includes('/play')));
});

test('character is shared by draft frames, save and reloading another tab',async()=>{
  const f=fixture();await f.ready();await f.frame();
  assert.equal(f.get('skin').value,'none');
  f.get('skin').value='cat';f.get('skin').onchange();await f.frame();
  const frame=JSON.parse(f.calls.filter(x=>x.url.endsWith('/frame')).at(-1).options.body);
  assert.equal(frame.skin,'cat');assert.equal(f.get('lcd-play').disabled,true);
  await f.get('apply').onclick();
  const saved=JSON.parse(f.calls.find(x=>x.url.endsWith('/runtime')&&x.options.method==='POST').options.body);
  assert.equal(saved.skin,'cat');
  f.external({skin:'human'});await f.get('reload-settings').onclick();
  assert.equal(f.get('skin').value,'human');
  assert.ok(f.calls.every(x=>!x.url.includes('/play')&&!x.url.includes('/motion')));
});

test('character labels change language without losing the selected skin',async()=>{
  const f=fixture();await f.ready();f.get('skin').value='cat';
  f.document.documentElement.lang='en';f.events['dashboard:langchange']();
  assert.equal(f.get('skin').value,'cat');
  assert.equal(f.get('skin').children.find(x=>x.value==='cat').text,'Kitten');
});
