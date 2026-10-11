import { request, poll } from './transport.js';
import { nowSeconds } from './model.js';
import { showError, text, tr, el } from './ui.js';
import { fields, directions, settingsValid, settingsPulse } from './manual-settings-model.js?v=device-profiles-3';

const arrows={forward:'↑',backward:'↓',left:'←',right:'→'};
const labels = {forward:['Przód','Forward'],backward:['Tył','Backward'],left:['Lewo','Left'],right:['Prawo','Right']};

export class ManualSettings {
  constructor(safety) {
    this.safety=safety;this.state=null;this.pending={};this.directionEdits={};
    this.busy=false;this.draftRevision=null;this.selectedProfile=null;
    this.build();
    document.getElementById('motion-profile-select')?.addEventListener('change',event=>{
      this.selectedProfile=event.target.value;
      const name=document.getElementById('motion-profile-name');
      if(name)name.value=this.state?.profiles?.[this.selectedProfile]?.name||'';
      this.paint();
    });
    for(const [id,action] of [['motion-profile-apply','apply'],['motion-profile-create','create'],
      ['motion-profile-save','save'],['motion-profile-delete','delete']]){
      document.getElementById(id)?.addEventListener('click',()=>this.profile(action).catch(showError));
    }
    document.getElementById('manual-settings-save')?.addEventListener('click',()=>this.save().catch(showError));
    this.poller=poll(()=>this.refresh(),{interval:1000,onError:error=>{
      this.state=null;this.paint();this.safety.render();showError(error);
    }});
    window.addEventListener('pagehide',()=>this.poller.stop());
    window.addEventListener('dashboard:langchange',()=>this.paint());
  }
  dirty(){return Object.keys(this.pending).length>0 || Object.keys(this.directionEdits).length>0;}
  ready(){return !this.busy && !this.dirty() && settingsValid(this.state,nowSeconds());}
  editable(){return settingsValid(this.state,nowSeconds()) && ['DISARMED','ARMED'].includes(this.safety.state?.state)
    && !this.busy;}
  pulse(direction){
    if(!this.ready())throw new Error('manual_settings_unconfirmed');
    return settingsPulse(this.state,direction);
  }
  edit(callback){
    if(!this.editable())return;
    if(this.draftRevision===null)this.draftRevision=this.state.revision;
    callback();this.paint();this.safety.render();
  }
  input(id, caption, update){
    const label=el('label','motion-setting-field'), node=el('input');node.id=id;node.type=id.endsWith('-speed')?'range':'number';node.step='any';node.inputMode='decimal';
    label.dataset.field=node.type==='range'?'speed':'number';
    const title=el('span','',caption);label.append(title,node);
    if(node.type==='range'){const output=el('output');output.id=id+'-value';label.append(output);}
    node.addEventListener('input',()=>this.edit(()=>update(Number(node.value))));
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
        ['speed','Siła polecenia','Command magnitude'],['duration','Czas (s)','Duration (s)'],
        ...(calibration?[['minimum','Minimum','Minimum'],['maximum','Maksimum','Maximum'],['step','Krok','Step']]:[])
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
        [['linear_rate','linear_deceleration'],'↑ ↓ Jazda','↑ ↓ Travel'],
        [['turn_rate','turn_deceleration'],'← → Skręt','← → Turn'],
        [['reversal_pause'],'Nawrót','Reversal']
      ]){
        const group=el('fieldset','motion-smoothing-group');
        group.append(el('legend','',tr(pl,en)));
        for(const key of keys){
          const caption=key==='reversal_pause'?tr('Przerwa (s)','Pause (s)')
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
      if(!result.canonical || !settingsValid(result.data,nowSeconds()))throw new Error('manual_settings_unconfirmed');
      if(!this.state || result.data.revision>=this.state.revision)this.state=result.data;
      this.paint();this.safety.render();return this.state;
    }catch(error){
      this.state=null;this.paint();this.safety.render();throw error;
    }
  }
  async save(){
    if(this.busy || !this.dirty())return;
    if(!this.editable())throw new Error(tr('Poczekaj na aktualny stan robota przed zmianą ustawień.','Wait for current robot state before changing settings.'));
    this.busy=true;this.safety.render();
    const patch={revision:this.draftRevision,values:this.pending,directions:this.directionEdits};
    this.pending={};this.directionEdits={};this.draftRevision=null;
    try{
      const result=await request('/api/calibration/controls',{method:'POST',body:patch});
      if(!result.canonical || !settingsValid(result.data,nowSeconds()))throw new Error('manual_settings_unconfirmed');
      this.state=result.data;
      text('manual-settings-result',tr('Zapisano ustawienia na robocie.','Settings saved on the robot.'));
    }catch(error){
      this.state=null;
      try{await this.refresh();}catch{}
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
    this.busy=true;this.paint();this.safety.render();
    try{
      const result=await request('/api/calibration/controls',{method:'POST',body:{
        revision:this.draftRevision??this.state.revision,values:this.pending,
        directions:this.directionEdits,profile:operation}});
      if(!result.canonical || !settingsValid(result.data,nowSeconds()))throw new Error('manual_settings_unconfirmed');
      this.state=result.data;
      this.pending={};this.directionEdits={};this.draftRevision=null;
      this.selectedProfile=this.state.active_profile||'';
      const name=document.getElementById('motion-profile-name');
      if(name)name.value=this.state.profiles?.[this.selectedProfile]?.name||'';
      text('manual-settings-result',action==='delete'
        ?tr('Usunięto profil. Bieżące nastawy pozostały.','Profile deleted. Current settings retained.')
        :tr('Profil zapisany / zastosowany. Ruch nie został uruchomiony.','Profile saved / applied. No motion started.'));
    }catch(error){
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
    this.paintProfiles(known,editable);
    for(const name of directions){
      text('setting-'+name+'-title',tr(...labels[name]));
      if(known){
        const item=this.state.directions[name], v=this.state.values;
        const a=['forward','backward'].includes(name)?v.linear_rate:v.turn_rate;
        const d=['forward','backward'].includes(name)?v.linear_deceleration:v.turn_deceleration;
        const peak=Math.min(item.speed,item.duration/(1/a+1/d));
        text('setting-'+name+'-hint',tr('Zakres ','Range ')+item.minimum+'–'+item.maximum
          +tr(' · szczyt impulsu ≤',' · pulse peak ≤')+peak.toFixed(3));
      }
      for(const key of ['speed','duration','minimum','maximum','step']){
        const node=document.getElementById('setting-'+name+'-'+key);if(!node)continue;
        node.disabled=!editable;
        if(known && !(key in (this.directionEdits[name]||{}))){
          node.min=key==='duration'?.01:0;node.max=key==='duration'?.25:key==='step'?1:key==='speed'?this.state.directions[name].maximum:this.state.values.speed_limit;
          node.step=key==='speed'?this.state.directions[name].step:'any';
          node.value=this.state.directions[name][key];
        }
        if(key==='speed')text(node.id+'-value',Number(known && !('speed' in (this.directionEdits[name]||{})) ? this.state.directions[name].speed : node.value).toFixed(3));
      }
    }
    for(const key of fields){
      const node=document.getElementById('setting-'+key);if(!node)continue;
      node.disabled=!editable;
      if(known && !(key in this.pending)){
        node.value=this.state.values[key];node.max=this.state.limits[key];
        node.min=key==='reversal_pause'?0:.001;
      }
    }
    const save=document.getElementById('manual-settings-save');if(save)save.disabled=!editable || !this.dirty();
    text('manual-settings-status',known
      ?tr('Ustawienia robota · rewizja ','Robot settings · revision ')+this.state.revision
        +(this.dirty()?tr(' · niezapisane zmiany',' · unsaved changes'):'')
      :tr('Brak potwierdzonych ustawień robota','Robot settings unconfirmed'));
  }
}
