import { request } from './transport.js';
import { tr, showError, text } from './ui.js';
export class RemoteNavigation {
  constructor(safety) {
    this.safety=safety; this.policy=null; this.pending=false;
    document.getElementById('remote-load')?.addEventListener('click',()=>this.load().catch(showError));
    document.getElementById('remote-save')?.addEventListener('click',()=>this.save().catch(showError));
    document.getElementById('remote-arm')?.addEventListener('click',()=>this.arm().catch(showError));
    document.getElementById('remote-observe')?.addEventListener('click',()=>this.run(false).catch(showError));
    document.getElementById('remote-drive')?.addEventListener('click',()=>this.run(true).catch(showError));
    document.getElementById('remote-stop')?.addEventListener('click',()=>this.stop().catch(showError));
  }
  async load() {
    this.policy=(await request('/api/navigation/config')).data;
    for(const field of ['mode','speed','decision_budget_ms','max_motion_ms','calibration_id','model_sha256']) {
      document.getElementById('remote-'+field).value=this.policy[field];
    }
    document.getElementById('remote-corridor').value=this.policy.corridor.join(',');
    document.getElementById('remote-verified').checked=this.policy.verified===true;
    const status=(await request('/api/navigation/status')).data;
    text('remote-state',status.stale?tr('Stan pętli nieznany lub nieaktualny.','Loop state unknown or stale.'):
      `${status.running?tr('aktywna','running'):tr('zatrzymana','stopped')} · ${status.decision?.state||'unknown'} · ${status.stop_reason||''}`);
  }
  async save() {
    if(!this.policy)return;
    const values={};
    for(const field of ['mode','speed','decision_budget_ms','max_motion_ms','calibration_id','model_sha256']) {
      const value=document.getElementById('remote-'+field).value;
      values[field]=['speed','decision_budget_ms','max_motion_ms'].includes(field)?Number(value):value;
    }
    values.corridor=document.getElementById('remote-corridor').value.split(',').map(Number);
    values.verified=document.getElementById('remote-verified').checked;
    await request('/api/navigation/config',{method:'POST',body:{revision:this.policy.revision,values}});
    await this.load();
  }
  async arm() {
    const plan=document.getElementById('remote-plan').value.trim();
    if(!plan)throw new Error(tr('Wpisz plan krótkiej próby jazdy.','Enter a short driving trial plan.'));
    await this.safety.send('arm',{owner:'navigation',arming_mode:'timed',lease_s:10,
      operator_consent:true,operator_plan:plan},'/api/safety','navigation');
  }
  async run(drive) {
    if(drive&&this.policy?.mode!=='drive')throw new Error(tr('Zapisz tryb jazdy i odebraną kalibrację.','Save drive mode and accepted calibration.'));
    const name=drive?'s14_venom_navigation':'s15_venom_perception';
    const body={enabled:true,options:{}};
    if(drive) {
      await this.safety.prepare();
      const envelope=this.safety.envelope('move',{},'navigation');
      body.settings_revision=this.safety.state?.manual_settings?.revision;
      for(const key of ['generation','seq','source','ts','ttl_ms','request_id'])body[key]=envelope[key];
    }
    await request('/api/logic/feature/'+name,{method:'POST',body,timeout:20000});
    text('remote-state',tr('Żądanie startu wysłane; obserwuj rzeczywisty stan celu.','Start requested; observe actual goal state.'));
  }
  async stop() {
    await this.safety.stop();
    for(const name of ['s14_venom_navigation','s15_venom_perception'])
      await request('/api/logic/feature/'+name,{method:'POST',body:{enabled:false}});
    text('remote-state',tr('Pętla zatrzymana. Ponowny start wymaga nowej intencji.','Loop stopped. Restart requires a new intent.'));
  }
}
