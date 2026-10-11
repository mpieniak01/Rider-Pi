(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const clone = x => JSON.parse(JSON.stringify(x));
  const tr = (pl,en) => document.documentElement.lang.startsWith('en') ? en : pl;
  const names = {blink:['Mrugnięcie','Blink'],look:['Spojrzenie','Gaze'],neutral:['Neutralna','Neutral'],happy:['Radosna','Happy'],sad:['Smutna','Sad'],calm:['Spokojna','Calm'],curious:['Ciekawa','Curious'],surprised:['Zaskoczona','Surprised'],sleepy:['Senna','Sleepy']};
  const labels = {'eyes.dx':['← Oczy →','← Eyes →'],'eyes.dy':['↑ Oczy ↓','↑ Eyes ↓'],'eyes.blink':['Powieki','Eyelids'],'brows.lift':['Brwi ↑↓','Brows ↑↓'],'brows.tilt':['Brwi ↗↘','Brows ↗↘'],'mouth.open':['Usta','Mouth'],'mouth.curve':['Uśmiech','Smile']};
  const transitions = {original:['Z gestu','From gesture'],lin:['Liniowe','Linear'],in_out:['Łagodne','Smooth'],in:['Narastające','Ease in'],out:['Wygasające','Ease out']};
  let fields=[], bounds={}, meta, settings, gestures=[], spec, selected=null, poses=[];
  let playing=false, at=0, startedAt=0, startedTime=0, dirty=false, settingsDirty=false, valid=true;
  let busy=false, frameAbort=null, imageURL=null, frameBlob=null, revision=0, rendered='';
  let timer=null, pollTimer=null, runtimeState={}, settingsRevision=null, renderError=false, retries=0;
  const status=(pl,en=pl)=>{$('studio-status').textContent=tr(pl,en);};
  function errorMessage(code) {
    const map={lcd_unavailable:['LCD jest niedostępny na tym urządzeniu.','LCD is unavailable on this device.'],face_settings_conflict:['Ustawienia zmieniono w innej karcie. Wczytaj je przed zapisem.','Settings changed in another tab. Reload before saving.'],name_required:['Wpisz nazwę gestu.','Enter a gesture name.'],unknown_gesture:['Gest nie jest dostępny. Odśwież bibliotekę.','Gesture is unavailable. Refresh the library.'],gesture_not_active:['Dodaj gest do zestawu i zapisz ustawienia.','Include the gesture in the set and save settings.'],lcd_owned_or_unknown:['LCD jest używany przez inną funkcję.','LCD is used by another feature.'],face_not_running:['Buźka nie jest uruchomiona.','The face is not running.'],library_full:['Biblioteka jest pełna.','Library is full.']};
    return map[code]?tr(...map[code]):tr('Nie udało się wykonać operacji. Sprawdź ustawienia.','Operation failed. Check the settings.');
  }
  async function api(path,method='GET',body) {
    const response=await fetch('/api/face-studio/'+path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
    const data=await response.json();
    if(!response.ok||data.ok===false)throw Error(errorMessage(data.error));
    return data;
  }
  function duration(){return spec.duration/(Number($('tempo').value)/100);}
  function tuning() {
    return {style:$('style').value,skin:$('skin').value,intensity:Number($('intensity').value)/100,tempo:Number($('tempo').value)/100,transition:$('transition').value};
  }
  function updateSettingsStatus() {
    $('settings-status').textContent=settingsDirty?tr('Niezapisane ustawienia podglądu.','Unsaved preview settings.'):tr('Ustawienia zapisane na tym robocie.','Settings saved on this robot.');
    $('lcd-play').disabled=settingsDirty||dirty||!valid||!selected?.id;
  }
  function invalidate() {
    revision++;rendered='';retries=0;if(frameAbort)frameAbort.abort();wake();
  }
  function updateTuning() {
    $('intensity-value').textContent=$('intensity').value+'%';
    $('tempo-value').textContent=$('tempo').value+'%';
    if(spec){$('scrub').max=Math.round(duration()*1000);at=Math.min(at,duration());}
    playing=false;settingsDirty=true;updateSettingsStatus();invalidate();
  }
  function setupMeta(data) {
    meta=data.descriptors;settings=data.settings;settingsRevision=data.settings_revision;bounds=data.fields;fields=Object.keys(bounds);
    $('style').replaceChildren();meta.styles.forEach(s=>$('style').add(new Option(tr(s.pl,s.en),s.id)));
    $('skin').replaceChildren();meta.skins.forEach(s=>$('skin').add(new Option(tr(s.pl,s.en),s.id)));
    $('expression').replaceChildren();meta.expressions.forEach(id=>$('expression').add(new Option(names[id]?tr(...names[id]):id,id)));
    $('transition').replaceChildren();meta.transitions.forEach(id=>$('transition').add(new Option(tr(...transitions[id]),id)));
    for(const id of ['intensity','tempo'])Object.assign($(id),{min:meta[id].min,max:meta[id].max,step:meta[id].step,value:Math.round(settings[id]*100)});
    applySettings(settings);
  }
  function applySettings(data) {
    settings=clone(data);playing=false;
    for(const id of ['intensity','tempo'])$(id).value=Math.round(settings[id]*100);
    $('style').value=settings.style;$('skin').value=settings.skin??'none';$('transition').value=settings.transition;$('power-mode').value=settings.power_mode;$('idle').checked=settings.idle;
    $('intensity-value').textContent=$('intensity').value+'%';$('tempo-value').textContent=$('tempo').value+'%';
    if(spec){at=Math.min(at,duration());$('scrub').max=Math.round(duration()*1000);}
  }
  function ease(kind,t) {if(kind==='in')return t*t;if(kind==='out')return 1-(1-t)**2;if(kind==='in_out')return t*t*(3-2*t);return t;}
  function valueAt(field,time) {
    let value=spec.initial?.[field]??meta.expression_defaults[spec.expr]?.[field]??0;
    for(const s of spec.tracks[field]||[]){
      if(time<s.t0)break;
      if(time>=s.t1)value=s.v1;
      else{value=s.v0+(s.v1-s.v0)*ease(s.ease,(time-s.t0)/(s.t1-s.t0));break;}
    }
    return Math.round(value*100);
  }
  function showPoses() {
    const head=document.createElement('tr');
    ['ms',...fields.map(f=>labels[f]?tr(...labels[f]):f),tr('Przejście','Transition'),''].forEach(label=>{const th=document.createElement('th');th.textContent=label;head.append(th);});
    $('pose-head').replaceChildren(head);$('poses').replaceChildren();
    poses.forEach((pose,index)=>{
      const row=document.createElement('tr');
      ['time',...fields].forEach(field=>{
        const td=document.createElement('td'),input=document.createElement('input');
        input.type='number';input.step=field==='time'?meta.duration.step:1;
        input.min=field==='time'?0:bounds[field][0]*100;input.max=field==='time'?meta.duration.max:bounds[field][1]*100;
        input.value=pose[field];input.disabled=field==='time'&&index===0;input.setAttribute('aria-label',(labels[field]?tr(...labels[field]):'ms')+' — '+(index+1));
        input.oninput=()=>{pose[field]=input.valueAsNumber;rebuild();};td.append(input);row.append(td);
      });
      const td=document.createElement('td'),select=document.createElement('select');
      meta.transitions.filter(v=>v!=='original').forEach(v=>select.add(new Option(tr(...transitions[v]),v)));
      select.value=pose.ease;select.disabled=index===0;select.setAttribute('aria-label',tr('Przejście','Transition'));
      select.onchange=()=>{pose.ease=select.value;rebuild();};td.append(select);row.append(td);
      const end=document.createElement('td'),remove=document.createElement('button');remove.textContent='×';remove.title=tr('Usuń pozę','Remove pose');remove.disabled=index===0;
      remove.onclick=()=>{poses.splice(index,1);showPoses();rebuild();};end.append(remove);row.append(end);$('poses').append(row);
    });
  }
  function rebuild() {
    playing=false;dirty=true;valid=false;
    try{
      if(poses.length<2)throw Error(tr('Dodaj pozę końcową.','Add an ending pose.'));
      let previous=-1;
      poses.forEach(p=>{
        if(!Number.isFinite(p.time)||p.time<=previous||p.time>meta.duration.max)throw Error(tr('Czasy muszą rosnąć.','Times must increase.'));
        previous=p.time;
        fields.forEach(f=>{if(!Number.isFinite(p[f])||p[f]>bounds[f][1]*100||p[f]<bounds[f][0]*100)throw Error(tr('Sprawdź zakres wartości.','Check value ranges.'));});
      });
      const tracks={};fields.forEach(f=>{tracks[f]=poses.slice(1).map((p,i)=>({t0:poses[i].time/1000,t1:p.time/1000,v0:poses[i][f]/100,v1:p[f]/100,ease:p.ease}));});
      spec={name:$('name').value,expr:$('expression').value,duration:poses.at(-1).time/1000,initial:Object.fromEntries(fields.map(f=>[f,poses[0][f]/100])),tracks,contract_version:meta.contract_version};
      valid=true;$('scrub').max=Math.round(duration()*1000);at=Math.min(at,duration());
      status('Niezapisany gest.','Unsaved gesture.');invalidate();
    }catch(error){status(error.message);}
    $('save').disabled=!valid;$('update').disabled=!valid||!selected?.id||selected.builtin;updateSettingsStatus();
  }
  function load(item) {
    playing=false;dirty=false;valid=true;selected=item;spec=clone(item);at=0;
    $('name').value=spec.name;$('expression').value=spec.expr;
    const times=new Set([0,spec.duration]);Object.values(spec.tracks).flat().forEach(s=>{times.add(s.t0);times.add(s.t1);});
    poses=[...times].sort((a,b)=>a-b).map(t=>({time:Math.round(t*1000),ease:Object.values(spec.tracks).flat().find(s=>Math.abs(s.t1-t)<1e-6)?.ease||'lin',...Object.fromEntries(fields.map(f=>[f,valueAt(f,t)]))}));
    showPoses();$('scrub').max=Math.round(duration()*1000);$('scrub').value=0;
    $('save').disabled=false;$('update').disabled=!item.id||item.builtin;$('delete').disabled=!item.id||item.builtin;
    $('active-gesture').checked=settings.active_gestures.includes(item.id);$('active-gesture').disabled=!item.id;
    updateSettingsStatus();status(item.builtin?'Gest wbudowany — możesz zapisać kopię.':'Gest wczytany.',item.builtin?'Built-in gesture — you can save a copy.':'Gesture loaded.');invalidate();
  }
  async function refresh(id,initial=false) {
    const data=await api('gestures');gestures=data.gestures;
    if(initial)setupMeta(data);else if(!settingsDirty){applySettings(data.settings);settingsRevision=data.settings_revision;}
    $('library').replaceChildren();gestures.forEach(g=>$('library').add(new Option((g.builtin?tr('Wbudowany: ','Built-in: '):'')+(g.builtin&&names[g.name]?tr(...names[g.name]):g.name),g.id)));
    const item=gestures.find(g=>g.id===id)||gestures[0];if(item){$('library').value=item.id;load(item);}
  }
  function clearImage(){if(imageURL)URL.revokeObjectURL(imageURL);imageURL=null;frameBlob=null;$('png').disabled=true;$('studio-image').removeAttribute('src');}
  function setImage(blob) {
    if(imageURL)URL.revokeObjectURL(imageURL);
    $('png').disabled=false;frameBlob=blob;imageURL=URL.createObjectURL(blob);$('studio-image').src=imageURL;
  }
  async function render() {
    if(busy||!spec||!valid||document.hidden)return;
    const live=$('source').value==='live',stamp=revision,time=at,key=live?'live':stamp+':'+time;
    if(!live&&rendered===key)return;
    busy=true;frameAbort=new AbortController();let retry=false;
    try{
      const response=await fetch('/api/face-studio/'+(live?'runtime/frame':'frame'),{
        method:live?'GET':'POST',signal:frameAbort.signal,
        headers:live?{}:{'Content-Type':'application/json'},
        body:live?undefined:JSON.stringify({...spec,...tuning(),simulate_speech:$('speech-preview').checked,at:time})
      });
      if(response.status===429){retry=true;return;}
      if(live&&response.status===404){clearImage();$('image-caption').textContent=tr('Buźka nie jest uruchomiona.','The face is not running.');return;}
      if(!response.ok)throw Error(tr('Nie udało się odczytać obrazu. Sprawdź czas i tempo.','Could not read the image. Check time and tempo.'));
      const blob=await response.blob();if(stamp!==revision||document.hidden)return;
      setImage(blob);rendered=key;retries=0;if(renderError){renderError=false;status(dirty?'Niezapisany gest.':'Gest wczytany.',dirty?'Unsaved gesture.':'Gesture loaded.');}
      $('image-caption').textContent=live?tr('Obraz aktywnego wykonawcy buźki.','Image from the active face worker.'):$('speech-preview').checked?tr('Podgląd · symulacja mówienia','Preview · simulated speech'):tr('Podgląd gestu · bez LCD','Gesture preview · without LCD');
      if(!live){$('scrub').value=Math.round(time*1000);$('time').textContent=Math.round(time*1000)+' ms';}
    }catch(error){if(error.name!=='AbortError'){playing=false;renderError=true;retry=++retries<=3;status(error.message==='Failed to fetch'?tr('Brak połączenia. Ponawiam odczyt obrazu.','Connection lost. Retrying the image.'):error.message);}}finally{busy=false;frameAbort=null;if(!document.hidden){if(retry)timer=setTimeout(wake,1000);else if(stamp!==revision)wake();}}
  }
  function wake() {
    if(timer!==null){clearTimeout(timer);timer=null;}
    if(document.hidden||!spec)return;
    timer=setTimeout(async()=>{
      timer=null;
      if(playing){at=startedAt+(performance.now()-startedTime)/1000;if(at>=duration()){if($('loop').checked)at%=duration();else{at=duration();playing=false;}}}
      await render();
      if(!document.hidden&&(playing||$('source').value==='live'))timer=setTimeout(wake,$('source').value==='live'&&!runtimeState.running?1000:1000/meta.fps.preview);
    },0);
  }
  function download(blob,name){const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  const discard=()=>!dirty||confirm(tr('Porzucić niezapisany gest?','Discard the unsaved gesture?'));
  $('library').onchange=()=>{if(discard())load(gestures.find(g=>g.id===$('library').value));else $('library').value=selected?.id||'';};
  $('play').onclick=()=>{if(!spec||!valid)return;if(at>=duration())at=0;playing=true;startedAt=at;startedTime=performance.now();wake();};
  $('pause').onclick=()=>{playing=false;wake();};$('rewind').onclick=()=>{playing=false;at=0;invalidate();};
  $('scrub').oninput=()=>{playing=false;at=Number($('scrub').value)/1000;invalidate();};
  $('zoom').onchange=()=>{$('studio-image').style.maxWidth=$('zoom').value+'px';};
  $('source').onchange=()=>{playing=false;clearImage();const live=$('source').value==='live';['play','pause','rewind','scrub','speech-preview'].forEach(id=>$(id).disabled=live);invalidate();};
  ['style','skin','intensity','tempo','transition'].forEach(id=>$(id).addEventListener(id==='intensity'||id==='tempo'?'input':'change',updateTuning));
  $('speech-preview').onchange=()=>{invalidate();};
  ['power-mode','idle'].forEach(id=>$(id).onchange=()=>{settingsDirty=true;updateSettingsStatus();});
  $('active-gesture').onchange=()=>{
    const ids=new Set(settings.active_gestures);if($('active-gesture').checked)ids.add(selected.id);else ids.delete(selected.id);
    settings.active_gestures=[...ids];settingsDirty=true;updateSettingsStatus();
  };
  $('name').oninput=()=>{dirty=true;spec.name=$('name').value;status('Niezapisany gest.','Unsaved gesture.');updateSettingsStatus();};
  $('expression').onchange=()=>{
    spec.expr=$('expression').value;spec.initial??={};
    fields.filter(f=>!spec.tracks[f]?.length).forEach(f=>spec.initial[f]=meta.expression_defaults[spec.expr]?.[f]??0);
    load({...spec,id:selected?.id,builtin:selected?.builtin});dirty=true;status('Niezapisany gest.','Unsaved gesture.');updateSettingsStatus();
  };
  $('new').onclick=()=>{if(discard()){load({name:tr('Nowy gest','New gesture'),expr:'neutral',duration:1,initial:{},tracks:{}});dirty=true;updateSettingsStatus();}};
  $('copy').onclick=()=>{load({...clone(spec),id:null,builtin:false,name:spec.name+tr(' — kopia',' — copy')});dirty=true;updateSettingsStatus();};
  $('add').onclick=()=>{if(poses.length>=33)return status('Maksymalnie 33 pozy','Maximum 33 poses');const p=clone(poses.at(-1));p.time+=250;poses.push(p);showPoses();rebuild();};
  async function save(update){try{const result=await api('gestures','POST',{...spec,id:update?selected.id:undefined});await refresh(result.id);status('Zapisano gest. Zapis nie uruchamia LCD.','Gesture saved. Saving does not start the LCD.');}catch(error){status(error.message);}}
  $('save').onclick=()=>save(false);$('update').onclick=()=>save(true);
  $('delete').onclick=async()=>{if(!confirm(tr('Usunąć gest?','Delete gesture?')))return;try{await api('gestures/'+encodeURIComponent(selected.id),'DELETE');await refresh();}catch(error){status(error.message);}};
  $('export').onclick=()=>download(new Blob([JSON.stringify({...spec,id:undefined,builtin:undefined},null,2)],{type:'application/json'}),'face-gesture.json');
  $('png').onclick=()=>{if(frameBlob)download(frameBlob,'face-frame.png');};
  $('import').onchange=async()=>{try{
    const file=$('import').files[0];if(!file||!discard())return;if(file.size>65536)throw Error('Max 64 KB');
    const raw=JSON.parse(await file.text()),item={name:raw.name,expr:raw.expr??'neutral',duration:raw.duration??1,initial:raw.initial??{},tracks:raw.tracks??{},contract_version:raw.contract_version??meta.contract_version};
    const response=await fetch('/api/face-studio/frame',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...item,at:0})});
    if(!response.ok)throw Error(tr('Nieprawidłowy gest.','Invalid gesture.'));load({...item,id:null,builtin:false});dirty=true;updateSettingsStatus();status('Import jako szkic — zapisz gest.','Imported as a draft — save the gesture.');
  }catch(error){status(error.message);}finally{$('import').value='';}};
  async function poll() {
    if(document.hidden)return;
    try{
      const result=await api('runtime');runtimeState=result.state;
      if(result.settings_revision!==settingsRevision&&!settingsDirty){applySettings(result.settings);settingsRevision=result.settings_revision;if(selected)$('active-gesture').checked=settings.active_gestures.includes(selected.id);updateSettingsStatus();invalidate();}
      const mode=result.settings.power_mode==='battery'?tr('bateria','battery'):tr('kabel','cable');
      $('runtime-status').textContent=runtimeState.error?errorMessage(runtimeState.error):runtimeState.running?tr('Buźka działa','Face running')+' · '+runtimeState.sink+' · '+runtimeState.fps+' FPS':tr('Buźka wyłączona','Face stopped')+' · '+mode;
    }catch(error){$('runtime-status').textContent=error.message;}
    if(!document.hidden)pollTimer=setTimeout(poll,2000);
  }
  $('apply').onclick=async()=>{try{
    const result=await api('runtime','POST',{...tuning(),power_mode:$('power-mode').value,idle:$('idle').checked,active_gestures:settings.active_gestures,if_revision:settingsRevision});
    settings=result.settings;settingsRevision=result.settings_revision;settingsDirty=false;updateSettingsStatus();status('Ustawienia zapisane. LCD nie został uruchomiony.','Settings saved. LCD was not started.');
  }catch(error){status(error.message);}};
  $('reload-settings').onclick=async()=>{try{const result=await api('runtime');applySettings(result.settings);settingsRevision=result.settings_revision;settingsDirty=false;if(selected)$('active-gesture').checked=settings.active_gestures.includes(selected.id);updateSettingsStatus();if(spec){at=Math.min(at,duration());$('scrub').max=Math.round(duration()*1000);}invalidate();}catch(error){status(error.message);}};
  $('lcd-play').onclick=async()=>{try{
    await api('runtime/play','POST',{sink:'lcd',gesture_id:selected.id,expr:spec.expr});status('Uruchomiono buźkę na LCD.','Face started on LCD.');
    if(pollTimer)clearTimeout(pollTimer);poll();
  }catch(error){status(error.message);}};
  $('lcd-stop').onclick=async()=>{try{await api('runtime/stop','POST',{});status('Buźka wyłączona.','Face stopped.');invalidate();if(pollTimer)clearTimeout(pollTimer);poll();}catch(error){status(error.message);}};
  document.addEventListener('visibilitychange',()=>{
    playing=false;if(timer!==null)clearTimeout(timer);timer=null;if(pollTimer!==null)clearTimeout(pollTimer);pollTimer=null;if(frameAbort)frameAbort.abort();
    if(!document.hidden){wake();poll();}
  });
  window.addEventListener('beforeunload',event=>{if(dirty||settingsDirty){event.preventDefault();event.returnValue='';}});
  window.addEventListener('dashboard:langchange',()=>{
    document.querySelectorAll('[data-pl][data-en]').forEach(node=>node.textContent=tr(node.dataset.pl,node.dataset.en));
    if(meta)for(const [id,items] of [['style',meta.styles],['skin',meta.skins]]){
      const selected=$(id).value;$(id).replaceChildren();items.forEach(s=>$(id).add(new Option(tr(s.pl,s.en),s.id)));$(id).value=selected;
    }
    showPoses();updateSettingsStatus();
  });
  refresh(undefined,true).then(()=>poll()).catch(error=>status(error.message));
})();