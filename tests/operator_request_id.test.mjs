import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {webcrypto} from 'node:crypto';
const file=new URL('../web/assets/operator/request-id.js',import.meta.url);
const source=await readFile(file,'utf8');
async function fixture(crypto){
 const module=new vm.SourceTextModule(source,{context:vm.createContext({crypto}),identifier:file.href});
 await module.link(()=>{});await module.evaluate();return module.namespace.requestId;
}
test('secure context request IDs remain unique',async()=>{
 const id=await fixture(webcrypto);const ids=new Set(Array.from({length:100},()=>id('fixture')));
 assert.equal(ids.size,100);assert.ok([...ids].every(value=>value.startsWith('fixture-')));
});
test('HTTP LAN uses getRandomValues when randomUUID is unavailable',async()=>{
 const id=await fixture({getRandomValues:webcrypto.getRandomValues.bind(webcrypto)});
 assert.match(id('lan'),/^lan-[0-9a-f]{32}$/);
});
test('a browser without cryptography fails before building a request',async()=>{
 const id=await fixture(undefined);assert.throws(()=>id(),/secure_randomness_unavailable/);
});
