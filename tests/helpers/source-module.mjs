// Load unchanged production modules in the current realm; V8 sees original file offsets.
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import vm from 'node:vm';
const modules=new Map();
async function getModule(value){
 const url=value instanceof URL?new URL(value):pathToFileURL(value);url.search='';
 if(!modules.has(url.href))modules.set(url.href,readFile(url,'utf8').then(source=>new vm.SourceTextModule(source,{identifier:url.href})));
 return modules.get(url.href);
}
export async function loadSource(value){
 const module=await getModule(value);
 if(module.status==='unlinked')await module.link((specifier,parent)=>getModule(new URL(specifier,parent.identifier)));
 if(module.status==='linked')await module.evaluate();
 return module.namespace;
}
