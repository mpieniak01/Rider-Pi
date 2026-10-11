import { text, tr } from './ui.js';

// Reuse the safety panel's confirmed state instead of a competing HTTP poll.
export class Calibration {
  constructor(safety) { this.safety=safety;this.render(); }
  render(){
    this.safety.controls?.paint();
    const state=this.safety.state;
    text('calibration-output',state
      ?JSON.stringify({target:state.target,output:state.output,sdk:state.sdk_output,
        settings_revision:state.manual_settings?.revision})
      :tr('Brak danych wykonawcy','Executor data unavailable'));
  }
}
