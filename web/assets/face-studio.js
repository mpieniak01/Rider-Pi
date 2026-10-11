(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const fields = ['eyes.dx','eyes.dy','eyes.blink','brows.lift','brows.tilt','mouth.open'];
  const clone = x => JSON.parse(JSON.stringify(x));
  const tr = (pl,en) => document.documentElement.lang.startsWith('en') ? en : pl;
  let gestures=[], spec, selected=null, poses=[], playing=false, at=0, last=0, dirty=false;
  let busy=false, imageURL=null, frameBlob=null, revision=0, rendered=-1;
  const status = (pl,en=pl) => { $('studio-status').textContent=tr(pl,en); };
  const names = {blink:['Mrugnięcie','Blink'],look:['Spojrzenie','Gaze'],neutral:['Neutralny','Neutral'],happy:['Radosny','Happy'],sad:['Smutny','Sad']};
  async function api(path, method='GET', body) {
    const res=await fetch('/api/face-studio/'+path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
    const data=await res.json(); if(!res.ok || data.ok===false) {
      const errors={name_required:['Wpisz nazwę gestu (1–60 znaków).','Enter a gesture name (1–60 characters).'],unknown_gesture:['Gest nie jest już dostępny. Odśwież bibliotekę.','Gesture is no longer available. Refresh the library.'],library_full:['Biblioteka jest pełna (200 gestów).','Library is full (200 gestures).']};
      throw Error(errors[data.error]?tr(...errors[data.error]):tr('Nie udało się zapisać lub odczytać gestu. Sprawdź wartości.','Could not save or read the gesture. Check the values.'));
    } return data;
  }
  function ease(kind,t) { if(kind==='in')return t*t; if(kind==='out')return 1-(1-t)**2; if(kind==='in_out')return t<.5?2*t*t:.5+.5*(1-(1-(t-.5)*2)**2); return t; }
  function valueAt(field,time) {
    let value=spec.initial?.[field]||0;
    for(const s of spec.tracks[field]||[]) {
      if(time<s.t0)break;
      if(time>=s.t1)value=s.v1;
      else {value=s.v0+(s.v1-s.v0)*ease(s.ease,(time-s.t0)/(s.t1-s.t0));break;}
    } return Math.round(value*100);
  }
  function showPoses() {
    $('poses').replaceChildren();
    poses.forEach((pose,index)=>{
      const row=document.createElement('tr');
      ['time',...fields].forEach(field=>{
        const td=document.createElement('td'), input=document.createElement('input');
        input.type='number'; input.step=field==='time'?'10':'1'; input.min=field==='time'?'0':(['eyes.blink','mouth.open'].includes(field)?'0':'-100'); input.max=field==='time'?'10000':'100';
        input.value=pose[field]; input.disabled=field==='time'&&index===0;
        input.setAttribute('aria-label',`${field} — ${index+1}`);
        input.addEventListener('input',()=>{pose[field]=input.valueAsNumber; rebuild();}); td.append(input); row.append(td);
      });
      const td=document.createElement('td'), select=document.createElement('select');
      [['lin','Liniowe','Linear'],['in_out','Łagodne','Smooth'],['in','Narastające','Ease in'],['out','Wygasające','Ease out']].forEach(([v,pl,en])=>select.add(new Option(tr(pl,en),v)));
      select.value=pose.ease; select.disabled=index===0; select.setAttribute('aria-label',tr('Przejście','Transition'));
      select.onchange=()=>{pose.ease=select.value;rebuild();}; td.append(select); row.append(td);
      const end=document.createElement('td'), remove=document.createElement('button'); remove.textContent='×'; remove.title=tr('Usuń pozę','Remove pose'); remove.disabled=index===0; remove.onclick=()=>{poses.splice(index,1);showPoses();rebuild();}; end.append(remove);row.append(end);$('poses').append(row);
    });
  }
  function rebuild() {
    playing=false;dirty=true;
    try {
      if(poses.length<2)throw Error(tr('Dodaj pozę końcową.','Add an ending pose.'));
      let previous=-1;
      poses.forEach(p=>{if(!Number.isFinite(p.time)||p.time<=previous||p.time>10000)throw Error(tr('Czasy muszą rosnąć, maks. 10 000 ms.','Times must increase, max. 10,000 ms.'));previous=p.time;fields.forEach(f=>{if(!Number.isFinite(p[f])||p[f]>(100)||p[f]<(['eyes.blink','mouth.open'].includes(f)?0:-100))throw Error(tr('Sprawdź zakres wartości.','Check value ranges.'));});});
      const tracks={}; fields.forEach(f=>{tracks[f]=poses.slice(1).map((p,i)=>({t0:poses[i].time/1000,t1:p.time/1000,v0:poses[i][f]/100,v1:p[f]/100,ease:p.ease}));});
      spec={name:$('name').value,expr:$('expression').value,duration:poses.at(-1).time/1000,initial:Object.fromEntries(fields.map(f=>[f,poses[0][f]/100])),tracks};
      $('scrub').max=poses.at(-1).time; at=Math.min(at,spec.duration); revision++;status('Niezapisane zmiany','Unsaved changes');
      $('save').disabled=false; $('update').disabled=!selected||selected.builtin;
    } catch(error) {status(error.message);$('save').disabled=true;$('update').disabled=true;}
  }
  function load(item) {
    playing=false;dirty=false;selected=item;spec=clone(item);at=0;revision++;
    $('name').value=spec.name;$('expression').value=spec.expr;
    const times=new Set([0,spec.duration]);Object.values(spec.tracks).flat().forEach(s=>{times.add(s.t0);times.add(s.t1);});
    poses=[...times].sort((a,b)=>a-b).map(t=>({time:Math.round(t*1000),ease:Object.values(spec.tracks).flat().find(s=>Math.abs(s.t1-t)<1e-6)?.ease||'lin',...Object.fromEntries(fields.map(f=>[f,valueAt(f,t)]))}));
    showPoses();$('scrub').max=spec.duration*1000;$('scrub').value=0;
    $('save').disabled=false;$('update').disabled=!item.id||item.builtin;$('delete').disabled=!item.id||item.builtin;
    status(item.builtin?'Gest wbudowany — edycję zapisz jako nowy.':'Gest wczytany.',item.builtin?'Built-in gesture — save edits as new.':'Gesture loaded.');
  }
  async function refresh(id) {
    const data=await api('gestures');gestures=data.gestures;$('library').replaceChildren();
    gestures.forEach(g=>$('library').add(new Option((g.builtin?tr('Wbudowany: ','Built-in: '):'')+(g.builtin&&names[g.name]?tr(...names[g.name]):g.name),g.id)));
    const item=gestures.find(g=>g.id===id)||gestures[0];if(item){$('library').value=item.id;load(item);}
  }
  async function render() {
    if(busy||!spec||document.hidden)return;
    const stamp=revision, time=at; if(rendered===`${stamp}:${time}`)return; busy=true;
    try {
      const res=await fetch('/api/face-studio/frame',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...spec,at:time})});
      if(!res.ok)throw Error(tr('Błąd podglądu.','Preview error.'));
      const blob=await res.blob(); if(stamp!==revision)return;
      if(imageURL)URL.revokeObjectURL(imageURL);frameBlob=blob;imageURL=URL.createObjectURL(blob);$('studio-image').src=imageURL;rendered=`${stamp}:${time}`;
      $('scrub').value=time*1000;$('time').textContent=Math.round(time*1000)+' ms';
    } catch(error){playing=false;status(error.message);} finally{busy=false;}
  }
  function download(blob,name) {const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  const discard = () => !dirty || confirm(tr('Porzucić niezapisane zmiany?','Discard unsaved changes?'));
  $('library').onchange=()=>{if(discard())load(gestures.find(g=>g.id===$('library').value));else $('library').value=selected?.id||'';};
  $('play').onclick=()=>{if(at>=spec.duration)at=0;playing=true;last=performance.now();};
  $('pause').onclick=()=>{playing=false;};$('rewind').onclick=()=>{playing=false;at=0;revision++;};
  $('scrub').oninput=()=>{playing=false;at=Number($('scrub').value)/1000;revision++;};
  $('zoom').onchange=()=>{$('studio-image').style.maxWidth=$('zoom').value+'px';};
  $('name').oninput=()=>{dirty=true;spec.name=$('name').value;revision++;status('Niezapisane zmiany','Unsaved changes');};
  $('expression').onchange=()=>{dirty=true;spec.expr=$('expression').value;revision++;status('Niezapisane zmiany','Unsaved changes');};
  $('new').onclick=()=>{if(discard()){load({name:tr('Nowy gest','New gesture'),expr:'neutral',duration:1,initial:{},tracks:{}});dirty=true;}};
  $('copy').onclick=()=>{load({...clone(spec),id:null,builtin:false,name:spec.name+tr(' — kopia',' — copy')});dirty=true;};
  $('add').onclick=()=>{if(poses.length>=33)return status('Maksymalnie 33 pozy','Maximum 33 poses');const p=clone(poses.at(-1));p.time+=250;poses.push(p);showPoses();rebuild();};
  async function save(update) {try{const data=await api('gestures','POST',{...spec,id:update?selected.id:undefined});await refresh(data.id);status('Zapisano gest.','Gesture saved.');}catch(e){status(e.message);}}
  $('save').onclick=()=>save(false);$('update').onclick=()=>save(true);
  $('delete').onclick=async()=>{if(!confirm(tr('Usunąć wybrany gest?','Delete selected gesture?')))return;try{await api('gestures/'+encodeURIComponent(selected.id),'DELETE');await refresh();}catch(e){status(e.message);}};
  $('export').onclick=()=>download(new Blob([JSON.stringify({...spec,id:undefined,builtin:undefined},null,2)],{type:'application/json'}),'face-gesture.json');
  $('png').onclick=()=>{if(frameBlob)download(frameBlob,'face-frame.png');};
  $('import').onchange=async()=>{try{const file=$('import').files[0];if(!file||!discard())return;if(file.size>65536)throw Error('Max 64 KB');const raw=JSON.parse(await file.text());const item={name:raw.name,expr:raw.expr??'neutral',duration:raw.duration??1,initial:raw.initial??{},tracks:raw.tracks??{}};const res=await fetch('/api/face-studio/frame',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...item,at:0})});if(!res.ok)throw Error(tr('Nieprawidłowy gest.','Invalid gesture.'));load({...item,id:null,builtin:false});dirty=true;status('Import jako szkic — zapisz, aby zachować.','Imported as draft — save to keep.');}catch(e){status(e.message);}finally{$('import').value='';}};
  document.addEventListener('visibilitychange',()=>{playing=false;});
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
  window.addEventListener('dashboard:langchange',()=>{document.querySelectorAll('[data-pl][data-en]').forEach(n=>{n.textContent=tr(n.dataset.pl,n.dataset.en);});showPoses();});
  setInterval(()=>{const now=performance.now();if(playing&&spec){at+=Math.min((now-last)/1000,.2);if(at>=spec.duration){if($('loop').checked)at%=spec.duration;else{at=spec.duration;playing=false;}}}last=now;render();},83);
  refresh().catch(e=>status(e.message));
})();
