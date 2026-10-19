// Real diagnostics renderer with in-memory DOM/fetch; no device or service mutations.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const file=new URL('../web/assets/pages/system.js',import.meta.url);
const source=await readFile(file,'utf8');
class Element{
 constructor(){this.children=[];this.classes=new Set();this.classList={toggle:(name,enabled)=>enabled?this.classes.add(name):this.classes.delete(name)};}
 append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function fixture(initial){
 const nodes=new Map(['system-graph','system-table','system-summary','system-network','status-line'].map(id=>[id,new Element()]));
 nodes.get('system-table').tHead=new Element();nodes.get('system-table').tBodies=[new Element()];
 let payload=initial,fail=false,tick;const calls=[],events=new Map();
 const context=vm.createContext({console:{warn(){}},AbortController,localStorage:{getItem:()=> 'en'},
  document:{documentElement:{lang:'en'},getElementById:id=>nodes.get(id),createElement:()=>new Element()},
  window:{addEventListener:(name,fn)=>events.set(name,fn)},setTimeout:()=>1,clearTimeout(){},setInterval:fn=>{tick=fn;return 1;},
  fetch:async(url,options)=>{calls.push({url,options});if(fail)throw Error('injected');return {ok:true,json:async()=>payload};}});
 const i18n=new vm.SyntheticModule(['initI18n','t'],function(){this.setExport('initI18n',()=>{});this.setExport('t',key=>key);},{context});
 const module=new vm.SourceTextModule(source,{context,identifier:file.href});await module.link(()=>i18n);await module.evaluate();await flush();
 return {nodes,calls,events,async update(value,error=false){payload=value;fail=error;await tick();await flush();}};
}
test('service diagnostics render groups, edges, statuses and network without mutations',async()=>{
 const f=await fixture({nodes:[{id:'api',unit:'api.service',label:'API',description:'HTTP',status:'active',group:'core',since:'today',edges_out:['voice']},
  {id:'voice',unit:'voice.service',label:'Voice',status:'failed',group:'voice'},
  {id:'other',unit:'other.service',status:'unexpected',group:'custom'}],network:{wifi:{status:'connected',addresses:['192.168.1.14'],default_route:true,autostart:false,gateway:'192.168.1.1'}}});
 assert.equal(f.nodes.get('system-table').tBodies[0].children.length,3);
 assert.equal(f.nodes.get('system-summary').children.length,4);
 assert.equal(f.nodes.get('system-graph').children.length,3);
 assert.equal(f.nodes.get('status-line').classes.has('is-stale'),false);
 assert.ok(f.calls.every(call=>call.url==='/api/services/graph'&&!call.options.method));
 f.events.get('dashboard:langchange')();
});
test('invalid or failed observations retain prior evidence but mark it stale',async()=>{
 const f=await fixture({nodes:[{id:'api',label:'API',unit:'api.service',status:'active'}]});
 const rows=f.nodes.get('system-table').tBodies[0].children;
 await f.update({nodes:[null]});assert.equal(f.nodes.get('status-line').classes.has('is-stale'),true);
 assert.equal(f.nodes.get('system-table').tBodies[0].children,rows);
 await f.update({},true);assert.equal(f.nodes.get('status-line').classes.has('is-stale'),true);
 await f.update({nodes:[],network:{wifi:null}});assert.equal(f.nodes.get('status-line').classes.has('is-stale'),false);
 assert.equal(f.nodes.get('system-table').tBodies[0].children.length,0);
});
test('no first observation cannot be presented as a healthy graph',async()=>{
 const f=await fixture({nodes:'invalid'});assert.equal(f.nodes.get('status-line').classes.has('is-stale'),true);
 assert.equal(f.nodes.get('system-graph').children.length,0);
});
