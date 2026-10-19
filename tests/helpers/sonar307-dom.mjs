// Inert DOM fixture: production creates actual element trees; HTML parsing is forbidden.
const escape=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
export function domNode(tag='div'){
  const listeners=new Map(),classes=new Set(),attributes=new Map();
  const node={tagName:tag.toUpperCase(),listeners,classes,attributes,children:[],dataset:{},value:'',
    classList:{add:value=>classes.add(value),remove:value=>classes.delete(value)},
    addEventListener:(event,handler)=>listeners.set(event,handler),
    setAttribute:(key,value)=>attributes.set(key,String(value)),
    append(...children){for(const child of children){child.parentElement=this;this.children.push(child);}},
    appendChild(child){this.append(child);},
    replaceChildren(...children){this.children=[];this._text='';this.append(...children);},
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;},
    querySelectorAll(selector){
      const action=selector.match(/data-action="([^"]+)"/)?.[1];
      return this.descendants().filter(child=>{
        if(action)return child.dataset.action===action;
        if(selector.startsWith('.'))return child.className?.split(' ').includes(selector.slice(1));
        return child.tagName===selector.toUpperCase();
      });
    },
    descendants(){return this.children.flatMap(child=>[child,...child.descendants()]);},
    fire(event,value){if(value!==undefined)this.value=value;return listeners.get(event)?.({target:this});},
  };
  Object.defineProperties(node,{
    textContent:{get(){return (this._text||'')+this.children.map(child=>child.textContent).join('');},
      set(value){this._text=String(value);this.children=[];}},
    controls:{get(){return new Map(this.descendants().filter(child=>child.dataset.action).map(child=>[child.dataset.action,child]));}},
    spans:{get(){return new Map(this.descendants().filter(child=>child.className).map(child=>['.'+child.className,child]));}},
    innerHTML:{get(){return escape(this._text||'')+this.children.map(serialize).join('');},
      set(){throw new Error('DOM fixture forbids innerHTML writes');}},
  });
  return node;
}
function serialize(node){
  const attributes=new Map(node.attributes);
  if(node.className)attributes.set('class',node.className);
  for(const [key,value] of Object.entries(node.dataset))attributes.set('data-'+key,value);
  for(const key of ['type','min','max','value'])if(node[key])attributes.set(key,node[key]);
  const attrs=[...attributes].map(([key,value])=>' '+key+'="'+escape(value)+'"').join('');
  return '<'+node.tagName.toLowerCase()+attrs+'>'+node.innerHTML+'</'+node.tagName.toLowerCase()+'>';
}
