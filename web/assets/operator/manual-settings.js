import { request, poll } from './transport.js';
import { nowSeconds } from './model.js';
import { showError, text, tr } from './ui.js';
import { settingsValid, settingsPulse } from './manual-settings-model.js';
const binding = { speed:'linear_speed', 'yaw-speed':'turn_speed', duration:'pulse_duration',
  'calibration-linear-speed':'linear_speed', 'calibration-turn-speed':'turn_speed', 'pulse-duration':'pulse_duration',
  'motion-speed-limit':'speed_limit', 'motion-linear-rate':'linear_rate', 'motion-turn-rate':'turn_rate' };
export class ManualSettings {
  constructor(safety) {
    this.safety=safety; this.state=null; this.pending={}; this.busy=false;
    for(const [id,key] of Object.entries(binding)) {
      const node=document.getElementById(id); if(!node) continue;
      node.disabled=true;
      node.addEventListener('input',()=>{
        this.pending[key]=Number(node.value); this.safety.render();
        clearTimeout(this.timer); this.timer=setTimeout(()=>this.save().catch(showError),200);
      });
    }
    this.poller=poll(()=>this.refresh(),{interval:1000,onError:error=>{
      this.state=null;this.paint();this.safety.render();showError(error);
    }});
    window.addEventListener('pagehide',()=>{clearTimeout(this.timer);this.poller.stop();});
  }
  ready(){return !this.busy && Object.keys(this.pending).length===0 && settingsValid(this.state,nowSeconds());}
  pulse(direction){if(!this.ready())throw new Error('manual_settings_unconfirmed');return settingsPulse(this.state,direction);}
  async refresh(){
    try {
      const result=await request('/api/calibration/controls');
      if(!result.canonical || !settingsValid(result.data,nowSeconds()))throw new Error('manual_settings_unconfirmed');
      this.state=result.data;this.paint();this.safety.render();return this.state;
    } catch(error) {
      this.state=null;this.paint();this.safety.render();throw error;
    }
  }
  async save(){
    if(this.busy || !Object.keys(this.pending).length)return;
    this.busy=true;this.safety.render();
    const patch=this.pending;this.pending={};
    try {
      if(!settingsValid(this.state,nowSeconds()))await this.refresh();
      const result=await request('/api/calibration/controls',{method:'POST',body:{revision:this.state.revision,values:patch}});
      if(!result.canonical || !settingsValid(result.data,nowSeconds()))throw new Error('manual_settings_unconfirmed');
      this.state=result.data;
    } catch(error) {
      this.pending={};this.state=null;
      try{await this.refresh();}catch{}
      throw error;
    } finally {
      this.busy=false;this.paint();this.safety.render();
      if(Object.keys(this.pending).length)this.save().catch(showError);
    }
  }
  paint(){
    const known=settingsValid(this.state,nowSeconds());
    for(const [id,key] of Object.entries(binding)){
      const node=document.getElementById(id);if(!node)continue;
      node.disabled=!known;
      if(known && !this.busy && !(key in this.pending)){
        node.max=this.state.limits[key];node.value=this.state.values[key];
        text(id+'-value',Number(node.value).toFixed(3));
      }
    }
    text('manual-settings-status',this.ready()
      ? tr('Wspólne ustawienia robota · wersja ','Shared robot settings · revision ')+this.state.revision
      : tr('Synchronizacja ustawień — ruch z panelu zablokowany','Synchronizing settings — panel movement blocked'));
  }
}
