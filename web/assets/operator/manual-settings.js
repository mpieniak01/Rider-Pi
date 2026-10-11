import { request, poll } from './transport.js';
import { nowSeconds } from './model.js';
import { showError, text, tr, el } from './ui.js';
import { fields, directions, settingsValid, settingsPulse, parameter, displayFactor, descriptionsValid } from './manual-settings-model.js?v=motion-descriptors-9';

const arrows={forward:'↑',backward:'↓',left:'←',right:'→'};
// Display units only: canonical Pi values stay normalized commands and seconds.

const displayNumber = value => Number((value).toFixed(6));
const percent = value => Number.isFinite(value) ? displayNumber(value * 100).toLocaleString(document.documentElement?.lang || 'pl', {maximumFractionDigits: 3})+'%' : '—';
const labels = {forward:['Przód','Forward'],backward:['Tył','Backward'],left:['Lewo','Left'],right:['Prawo','Right']};

export class ManualSettings {
  constructor(safety) {
    this.safety=safety;this.state=null;this.pending={};this.directionEdits={};
    this.busy=false;this.draftRevision=null;this.selectedProfile=null;this.profileSelectionDirty=false;
    this.build();
    document.getElementById('motion-profile-select')?.addEventListener('change',event=>{
      this.selectedProfile=event.target.value;this.profileSelectionDirty=true;
      const name=document.getElementById('motion-profile-name');
      if(name)name.value=this.state?.profiles?.[this.selectedProfile]?.name||'';
      this.paint();
    });
    for(const [id,action] of [['motion-profile-apply','apply'],['motion-profile-create','create'],
      ['motion-profile-save','save'],['motion-profile-delete','delete']]){
      document.getElementById(id)?.addEventListener('click',()=>this.profile(action).catch(error=>this.reportError(error)));
    }
    document.getElementById('manual-settings-save')?.addEventListener('click',()=>this.save().catch(error=>this.reportError(error)));
    this.poller=poll(()=>this.refresh(),{interval:1000,onError:error=>{
      this.state=null;this.paint();this.safety.render();this.reportError(error);
    }});
    window.addEventListener('pagehide',()=>this.poller.stop());
    window.addEventListener('dashboard:langchange',()=>this.paint());
  }
  dirty(){return Object.keys(this.pending).length>0 || Object.keys(this.directionEdits).length>0;}
  descriptor(key){return parameter(this.state,key);}
  factor(key){return displayFactor(this.state,key);}
  ready(){return !this.busy && !this.dirty() && settingsValid(this.state,nowSeconds()) && !this.validation().length;}
  editable(){return settingsValid(this.state,nowSeconds()) && ['DISARMED','ARMED'].includes(this.safety.state?.state)
    && !this.busy;}
  pulse(direction){
    if(!this.ready())throw new Error('manual_settings_unconfirmed');
    return settingsPulse(this.state,direction);
  }
  edit(callback){
    if(!this.editable())return;
    if(this.draftRevision===null)this.draftRevision=this.state.revision;
    text('operator-message','');text('manual-settings-result','');
    callback();this.paint();this.safety.render();
  }
  input(id, caption, update){
    const label=el('label','motion-setting-field'), node=el('input');node.id=id;node.type=id.endsWith('-speed')?'range':'number';node.step='any';node.inputMode='decimal';
    label.dataset.field=node.type==='range'?'speed':'number';
    const title=el('span','',caption);title.dataset.caption=caption;label.append(title,node);
    if(node.type==='range'){const output=el('output');output.id=id+'-value';label.append(output);}
    node.addEventListener('input',()=>this.edit(()=>{
      const key=id.replace(/^setting-(forward|backward|left|right)-/,'').replace(/^setting-/,'');
      let value=node.value.trim()==='' ? NaN : Number(node.value)/this.factor(key);
      if(node.type==='range' && Number.isFinite(value)){
        const direction=id.split('-')[1], item=this.effective().directions[direction];
        if(item.step>0 && item.step<=item.maximum-item.minimum){
          value=displayNumber(Math.min(item.maximum,Math.max(item.minimum,Math.round(value/item.step)*item.step)));
        }
      }
      update(value);
    }));
    return label;
  }
  build(){
    const target=document.getElementById('manual-direction-settings');if(!target)return;
    const calibration=document.body.dataset.page==='calibration';
    for(const name of directions){
      const row=el('div','motion-setting-row');row.dataset.directionSettings=name;
      const heading=el('strong','motion-direction');
      const arrow=el('span','motion-direction-arrow',arrows[name]);arrow.setAttribute('aria-hidden','true');
      const title=el('span','',tr(...labels[name]));title.id='setting-'+name+'-title';
      heading.append(arrow,title);row.append(heading);
      for(const [key,pl,en] of [
        ['speed','Siła (%)','Magnitude (%)'],['duration','Czas (ms)','Duration (ms)'],
        ...(calibration?[['minimum','Min. (%)','Min. (%)'],['maximum','Maks. (%)','Max. (%)'],['step','Krok (%)','Step (%)']]:[])
      ]){
        row.append(this.input('setting-'+name+'-'+key,tr(pl,en),value=>{
          this.directionEdits[name]={...this.directionEdits[name],[key]:value};
        }));
      }
      const hint=el('small','operator-muted motion-setting-hint','');hint.id='setting-'+name+'-hint';row.append(hint);target.append(row);
    }
    const ramps=document.getElementById('manual-smoothing-settings');
    if(ramps){
      for(const [keys,pl,en] of [
        [['linear_rate','linear_deceleration'],'↑ ↓ Jazda (%/s)','↑ ↓ Travel (%/s)'],
        [['turn_rate','turn_deceleration'],'← → Skręt (%/s)','← → Turn (%/s)'],
        [['reversal_pause'],'Nawrót','Reversal']
      ]){
        const group=el('fieldset','motion-smoothing-group');
        group.append(el('legend','',tr(pl,en)));
        for(const key of keys){
          const caption=key==='reversal_pause'?tr('Przerwa (ms)','Pause (ms)')
            :key.endsWith('deceleration')?tr('Hamowanie','Deceleration'):tr('Narastanie','Acceleration');
          group.append(this.input('setting-'+key,caption,value=>{this.pending[key]=value;}));
        }
        ramps.append(group);
      }
    }
  }
  async refresh(){
    try{
      const result=await request('/api/calibration/controls');
      if(!result.canonical || !settingsValid(result.data,nowSeconds()) || !descriptionsValid(result.data))throw new Error('manual_settings_unconfirmed');
      if(!this.state || result.data.revision>=this.state.revision){
        if(this.state?.active_profile!==result.data.active_profile && !this.profileSelectionDirty){
          this.selectedProfile=result.data.active_profile||'';
          const name=document.getElementById('motion-profile-name');
          if(name)name.value=result.data.profiles?.[this.selectedProfile]?.name||'';
        }
        this.state=result.data;
      }
      this.paint();this.safety.render();return this.state;
    }catch(error){
      this.state=null;this.paint();this.safety.render();throw error;
    }
  }
  effective(){
    if(!this.state)return null;
    const rows=Object.fromEntries(directions.map(name=>[name,{...this.state.directions[name],...this.directionEdits[name]}]));
    return {values:{...this.state.values,...this.pending,speed_limit:Math.max(...directions.map(name=>rows[name].maximum))},directions:rows};
  }
  validation(){
    const effective=this.effective();if(!effective)return [];
    const errors=[], add=(id,pl,en)=>errors.push({id,message:tr(pl,en)});
    const v=effective.values;
    for(const name of directions){
      const d=effective.directions[name], prefix='setting-'+name+'-', caption=tr(...labels[name])+': ';
      for(const key of ['speed','duration','minimum','maximum','step']){
        if(!Number.isFinite(d[key]))add(prefix+key,caption+'Wpisz liczbę.',caption+'Enter a number.');
      }
      if(!(d.duration>=this.descriptor('duration').minimum && d.duration<=this.descriptor('duration').maximum))add(prefix+'duration',caption+'Czas: '+this.descriptor('duration').minimum*this.factor('duration')+'–'+this.descriptor('duration').maximum*this.factor('duration')+' ms.',caption+'Duration: '+this.descriptor('duration').minimum*this.factor('duration')+'–'+this.descriptor('duration').maximum*this.factor('duration')+' ms.');
      if(!(d.minimum>=0 && d.minimum<=d.maximum))add(prefix+'minimum',caption+'Minimum musi mieścić się między 0 a maksimum.',caption+'Minimum must be between zero and maximum.');
      if(!(d.maximum>=0 && d.maximum<=this.descriptor('maximum').maximum))add(prefix+'maximum',caption+'Maksimum nie może przekroczyć '+percent(this.descriptor('maximum').maximum)+'.',caption+'Maximum cannot exceed '+percent(this.descriptor('maximum').maximum)+'.');
      if(!(d.step>0 && (d.maximum===d.minimum || d.step<=d.maximum-d.minimum)))add(prefix+'step',caption+'Krok musi być większy od 0 i nie większy od zakresu ('+percent(d.maximum-d.minimum)+').',caption+'Step must be positive and no larger than the range ('+percent(d.maximum-d.minimum)+').');
      if(!(d.speed===0 || d.speed>=d.minimum && d.speed<=d.maximum))add(prefix+'speed',caption+'Siła musi mieścić się w zakresie; 0 zatrzymuje.',caption+'Magnitude must be within the range; zero stops.');
      const a=v[name==='forward'||name==='backward'?'linear_rate':'turn_rate'];
      const dec=v[name==='forward'||name==='backward'?'linear_deceleration':'turn_deceleration'];
      const peak=d.duration/(1/a+1/dec);
      if(d.minimum>peak)add(prefix+'minimum',caption+'Impuls jest za krótki dla tego minimum (szczyt ≤'+percent(peak)+').',caption+'Pulse is too short for this minimum (peak ≤'+percent(peak)+').');
    }
    for(const key of ['linear_rate','turn_rate','linear_deceleration','turn_deceleration','reversal_pause']){
      const {minimum:min,maximum:cap}=this.descriptor(key);
      if(!Number.isFinite(v[key]) || v[key]<min || v[key]>cap){
        add('setting-'+key,'Wygładzanie: dopuszczalny zakres '+displayNumber(min*this.factor(key))+'–'+displayNumber(cap*this.factor(key))+(key==='reversal_pause'?' ms.':' %/s.'),
          'Smoothing: allowed range '+displayNumber(min*this.factor(key))+'–'+displayNumber(cap*this.factor(key))+(key==='reversal_pause'?' ms.':' %/s.'));
      }
    }
    return errors;
  }
  checkDraft(){
    const error=this.validation()[0];
    if(error){document.getElementById(error.id)?.focus?.();throw new Error(error.message);}
  }
  reportError(error){
    text('manual-settings-result','');
    const message=error.message==='manual_settings_direction_step_or_duration'
      ?tr('Zapis odrzucony: sprawdź krok oraz czas 10–1000 ms.','Write rejected: check the step and duration of 10–1000 ms.')
      :error.message;
    showError({...error,message});
  }
  async save(){
    if(this.busy || !this.dirty())return;
    if(!this.editable())throw new Error(tr('Poczekaj na aktualny stan robota przed zmianą ustawień.','Wait for current robot state before changing settings.'));
    this.checkDraft();
    this.busy=true;this.paint();this.safety.render();
    text('operator-message','');text('manual-settings-result',tr('Zapisywanie…','Saving…'));
    const patch={revision:this.draftRevision,values:{...this.pending},directions:Object.fromEntries(Object.entries(this.directionEdits).map(([name,row])=>[name,{...row}]))};
    try{
      const result=await request('/api/calibration/controls',{method:'POST',body:patch});
      if(!result.canonical || !settingsValid(result.data,nowSeconds()) || !descriptionsValid(result.data))throw new Error('manual_settings_unconfirmed');
      this.state=result.data;
      this.pending={};this.directionEdits={};this.draftRevision=null;
      text('manual-settings-result',tr('Zapis potwierdzony przez robota.','Save confirmed by the robot.'));
    }catch(error){
      text('manual-settings-result','');
      if(error.status!==400){
        this.pending={};this.directionEdits={};this.draftRevision=null;this.state=null;
        try{await this.refresh();}catch{}
      }
      if(error.status===409)error.message=tr(
        'Zapis odrzucony. Sprawdź aktualne wartości i zakończenie impulsu, następnie ponów zmianę.',
        'Write rejected. Review current values and pulse completion, then make the change again.');
      throw error;
    }finally{this.busy=false;this.paint();this.safety.render();}
  }
  async profile(action){
    if(!this.editable())throw new Error(tr('Poczekaj na aktualne ustawienia.','Wait for current settings.'));
    if(!['create','save'].includes(action) && this.dirty())throw new Error(tr('Najpierw zapisz zmienione nastawy.','Save changed settings first.'));
    const operation={action};
    if(action!=='create')operation.id=this.selectedProfile;
    if(['create','save'].includes(action)){
      operation.name=document.getElementById('motion-profile-name')?.value.trim();
      if(!operation.name)throw new Error(tr('Podaj nazwę profilu.','Enter a profile name.'));
    }
    if(['create','save'].includes(action))this.checkDraft();
    this.busy=true;this.paint();this.safety.render();
    text('operator-message','');text('manual-settings-result',tr('Zapisywanie…','Saving…'));
    try{
      const result=await request('/api/calibration/controls',{method:'POST',body:{
        revision:this.draftRevision??this.state.revision,values:this.pending,
        directions:this.directionEdits,profile:operation}});
      if(!result.canonical || !settingsValid(result.data,nowSeconds()) || !descriptionsValid(result.data))throw new Error('manual_settings_unconfirmed');
      this.state=result.data;
      this.pending={};this.directionEdits={};this.draftRevision=null;
      this.selectedProfile=this.state.active_profile||'';this.profileSelectionDirty=false;
      const name=document.getElementById('motion-profile-name');
      if(name)name.value=this.state.profiles?.[this.selectedProfile]?.name||'';
      text('manual-settings-result',action==='delete'
        ?tr('Usunięto profil. Bieżące nastawy pozostały.','Profile deleted. Current settings retained.')
        :tr('Profil zapisany / zastosowany. Ruch nie został uruchomiony.','Profile saved / applied. No motion started.'));
    }catch(error){
      text('manual-settings-result','');
      if(error.status===409){
        this.pending={};this.directionEdits={};this.draftRevision=null;
        await this.refresh();
        error.message=tr('Sprawdź aktualne nastawy i zakończenie impulsu, następnie ponów operację.','Review current settings and pulse completion, then retry.');
      }
      throw error;
    }finally{this.busy=false;this.paint();this.safety.render();}
  }
  paintProfiles(known,editable){
    const select=document.getElementById('motion-profile-select');if(!select)return;
    if(!known){
      select.disabled=true;
      for(const id of ['motion-profile-name','motion-profile-apply','motion-profile-create','motion-profile-save','motion-profile-delete']){
        const node=document.getElementById(id);if(node)node.disabled=true;
      }
      return;
    }
    const profiles=known?this.state.profiles||{}:{};
    const signature=JSON.stringify(profiles);
    if(this.selectedProfile===null && known)this.selectedProfile=this.state.active_profile||'';
    if(this.selectedProfile && !profiles[this.selectedProfile])this.selectedProfile='';
    if(select.dataset.profiles!==signature){
      const blank=el('option','',tr('Bieżące / własne nastawy','Current / custom settings'));blank.value='';
      select.replaceChildren(blank,...Object.entries(profiles).map(([id,row])=>{
        const option=el('option','',row.name);option.value=id;return option;
      }));select.dataset.profiles=signature;
    }
    select.value=this.selectedProfile||'';select.disabled=!editable;
    const selected=Boolean(profiles[this.selectedProfile]);
    for(const [id,enabled] of [['motion-profile-apply',selected&&!this.dirty()],
      ['motion-profile-create',true],['motion-profile-save',selected],['motion-profile-delete',selected&&!this.dirty()]]){
      const node=document.getElementById(id);if(node)node.disabled=!editable||!enabled;
    }
    const name=document.getElementById('motion-profile-name');
    if(name){name.disabled=!editable;if(name.dataset.initialized!== 'true' && known){
      name.value=profiles[this.selectedProfile]?.name||'';name.dataset.initialized='true';
    }}
    const active=profiles[this.state?.active_profile];
    text('motion-profile-status',active?tr('Aktywny: ','Active: ')+active.name
      +(this.state.profile_modified?tr(' · zmienione nastawy, profil nieaktualizowany',' · modified settings, preset not updated'):'')
      :tr('Własne nastawy — bez wybranego profilu','Custom settings — no active profile'));
  }
  paint(){
    const known=settingsValid(this.state,nowSeconds()), editable=this.editable();
    const effective=known?this.effective():null, errors=known?this.validation():[];
    this.paintProfiles(known,editable);
    for(const name of directions){
      text('setting-'+name+'-title',tr(...labels[name]));
      if(known){
        const item=effective.directions[name], v=effective.values;
        const a=['forward','backward'].includes(name)?v.linear_rate:v.turn_rate;
        const d=['forward','backward'].includes(name)?v.linear_deceleration:v.turn_deceleration;
        const peak=Math.min(item.speed,item.duration/(1/a+1/d));
        text('setting-'+name+'-hint',tr('Zakres ','Range ')+percent(item.minimum)+'–'+percent(item.maximum)+tr(' · krok ',' · step ')+percent(item.step));
        const row=document.getElementById('setting-'+name+'-title')?.closest('.motion-setting-row');
        if(row)row.title=tr('Teoretyczny szczyt impulsu od postoju: ','Theoretical pulse peak from rest: ')+percent(peak);
        text('setting-'+name+'-speed-value',Number.isFinite(item.speed)?percent(item.speed)+tr(' · impuls ≤',' · pulse ≤')+percent(peak):'—');
      }else text('setting-'+name+'-speed-value','—');
      for(const key of ['speed','duration','minimum','maximum','step']){
        const node=document.getElementById('setting-'+name+'-'+key);if(!node)continue;
        node.disabled=!editable;
        if(known){
          const caption=node.parentElement?.querySelector?.('span');
          if(caption?.dataset.caption)caption.textContent=caption.dataset.caption.replace(/\([^)]*\)/, '('+this.descriptor(key).display_unit+')');
          node.min=displayNumber(this.descriptor(key).minimum*this.factor(key));
          node.max=displayNumber((key==='speed'?Math.max(0,effective.directions[name].maximum):this.descriptor(key).maximum)*this.factor(key));
          // Browser step rounding must never rewrite an authoritative value.
          node.step='any';
          const value=effective.directions[name][key];
          if(Number.isFinite(value) && (key==='speed' || !(key in (this.directionEdits[name]||{}))))node.value=displayNumber(value*this.factor(key));
        }
        node.setAttribute?.('aria-invalid',String(errors.some(error=>error.id===node.id)));
      }
    }
    for(const key of fields){
      const node=document.getElementById('setting-'+key);if(!node)continue;
      node.disabled=!editable;
      if(known){
        const caption=node.parentElement?.querySelector?.('span');
        if(caption?.dataset.caption)caption.textContent=caption.dataset.caption.replace(/\([^)]*\)/, '('+this.descriptor(key).display_unit+')');
        node.max=displayNumber(this.descriptor(key).maximum*this.factor(key));
        node.min=displayNumber(this.descriptor(key).minimum*this.factor(key));node.step='any';
        if(!(key in this.pending))node.value=displayNumber(this.state.values[key]*this.factor(key));
      }
      node.setAttribute?.('aria-invalid',String(errors.some(error=>error.id===node.id)));
    }
    // A visible field error is attached to its input, not only to a page banner.
    for(const name of [...directions.flatMap(name=>['speed','duration','minimum','maximum','step'].map(key=>'setting-'+name+'-'+key)),
      ...fields.map(key=>'setting-'+key)]){
      const node=document.getElementById(name);if(!node?.parentElement)continue;
      let message=document.getElementById(name+'-error');
      if(!message){message=el('small','operator-error motion-field-error');message.id=name+'-error';node.parentElement.append(message);node.setAttribute('aria-describedby',message.id);}
      const error=errors.find(error=>error.id===name);message.textContent=error?.message||'';message.hidden=!error;
    }
    const feedback=document.getElementById('manual-settings-feedback');
    if(feedback){
      if(!known)feedback.textContent=tr('Brak potwierdzonych nastaw z Pi.','No confirmed settings from Pi.');
      else{
        const v=this.state.values, runtime=this.safety.state?.manual_settings;
        const matched=runtime?.revision===this.state.revision
          && fields.every(key=>runtime.values?.[key]===v[key])
          && directions.every(name=>['minimum','maximum','step','speed','duration'].every(key=>runtime.directions?.[name]?.[key]===this.state.directions[name][key]));
        feedback.textContent=(matched?tr('Wykonawca potwierdza nastawy. ','Executor confirms settings. '):tr('Oczekiwanie na potwierdzenie wykonawcy. ','Waiting for executor confirmation. '))
          +tr('Jazda ↑/↓: ','Travel ↑/↓: ')+percent(v.linear_rate)+'/s / '+percent(v.linear_deceleration)+'/s'
          +tr(' · Skręt ←/→: ',' · Turn ←/→: ')+percent(v.turn_rate)+'/s / '+percent(v.turn_deceleration)+'/s'
          +tr(' (narastanie / hamowanie) · Nawrót: ',' (acceleration / deceleration) · Reversal: ')+displayNumber(v.reversal_pause*1000)+' ms.'
          +(this.dirty()?tr(' Suwaki zawierają niezapisane zmiany.',' Sliders include unsaved edits.'):'');
      }
    }
    const save=document.getElementById('manual-settings-save');if(save)save.disabled=!editable || !this.dirty() || errors.length>0;
    for(const id of ['motion-profile-create','motion-profile-save']){
      const node=document.getElementById(id);if(node && errors.length)node.disabled=true;
    }
    text('manual-settings-status',known
      ?tr('Ustawienia robota · rewizja ','Robot settings · revision ')+this.state.revision
        +(this.dirty()?tr(' · niezapisane zmiany',' · unsaved changes'):'')
      :tr('Brak potwierdzonych ustawień robota','Robot settings unconfirmed'));
  }
}
