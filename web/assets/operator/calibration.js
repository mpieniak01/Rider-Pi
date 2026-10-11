import { request, poll } from './transport.js';
import { text, tr, showError } from './ui.js';

// Motion settings and arrows are shared with /control, not copied into a form profile.
export class Calibration {
  constructor(safety) {
    this.safety=safety;
    this.poller=poll(async()=>{
      const result=await request('/api/control/state');
      const state=result.data?.safety;
      if(state && state.contract_version===1)this.safety.update(state);
      text('calibration-output',state
        ?JSON.stringify({target:state.target,output:state.output,sdk:state.sdk_output,
          settings_revision:state.manual_settings?.revision})
        :tr('Brak danych wykonawcy','Executor data unavailable'));
    },{interval:1000,onError:showError});
    window.addEventListener('pagehide',()=>this.poller.stop());
  }
  render(){this.safety.controls?.paint();}
}
