import { tr, showError } from './ui.js';
export class Posture {
 constructor(safety) {
  this.dirty = new Set();
  this.safety=safety;this.root=document.getElementById('posture-controls');
  this.root.innerHTML='<h2 data-pl="Postawa robota" data-en="Robot posture">Postawa robota</h2><div class="posture-row"><label for="posture-height" data-pl="↕ Wysokość" data-en="↕ Height">↕ Wysokość</label><span data-pl="Niżej" data-en="Lower">Niżej</span><input id="posture-height" type="range" min="75" max="115" step="1" value="90" disabled><span data-pl="Wyżej" data-en="Higher">Wyżej</span><output>90</output><button class="c-btn" id="posture-height-send" type="button" data-pl="Ustaw" data-en="Apply">Ustaw</button></div><div class="posture-row"><label for="posture-balance" data-pl="Balansowanie przechyłu" data-en="Tilt balancing">Balansowanie przechyłu</label><select id="posture-balance" disabled><option value="" data-pl="Wybierz" data-en="Choose">Wybierz</option><option value="1" data-pl="Włączone" data-en="On">Włączone</option><option value="0" data-pl="Wyłączone" data-en="Off">Wyłączone</option></select><button class="c-btn" id="posture-balance-send" type="button" data-pl="Ustaw" data-en="Apply">Ustaw</button></div><p class="operator-muted" id="posture-state"></p><details><summary data-pl="Figury producenta" data-en="Manufacturer figures">Figury producenta</summary><div class="posture-row"><select id="posture-action"><option value="1" data-pl="Kołysanie" data-en="Rocking">Kołysanie</option><option value="2" data-pl="Ruch pionowy" data-en="Vertical motion">Ruch pionowy</option><option value="5" data-pl="Podniesienie i obrót" data-en="Lift and turn">Podniesienie i obrót</option><option value="6" data-pl="Ruch okrężny" data-en="Circular motion">Ruch okrężny</option><option value="255" data-pl="Pozycja domyślna / reset" data-en="Default posture / reset">Pozycja domyślna / reset</option></select><button class="c-btn" id="posture-action-send" type="button" data-pl="Wykonaj" data-en="Run">Wykonaj</button></div><p id="posture-action-status" class="operator-muted"></p></details>';
  this.height=this.root.querySelector('#posture-height');this.balance=this.root.querySelector('#posture-balance');
  this.height.oninput=()=>{this.dirty.add('height');this.root.querySelector('output').textContent=this.height.value;};
  this.balance.onchange=()=>this.dirty.add('balance');
  this.height.onchange=()=>this.send('height',{height:Number(this.height.value)});
  this.root.querySelector('#posture-height-send').onclick=()=>this.send('height',{height:Number(this.height.value)});
  this.root.querySelector('#posture-balance-send').onclick=()=>{if(this.balance.value!=='')this.send('balance',{enabled:this.balance.value==='1'});};
  this.root.querySelector('#posture-action-send').onclick=()=>this.send('action',{action_id:Number(this.root.querySelector('#posture-action').value)});
  window.addEventListener('dashboard:langchange',()=>this.render());
  this.render();
 }
 async send(action,params){
  if(this.busy || !this.safety.can('manual',action))return;
  this.busy=true;this.render();
  try{await this.safety.send(action,params);this.dirty.delete(action);}
  catch(error){showError(error);}
  finally{this.busy=false;this.render();}
 }
 render(){
  const language=document.documentElement.lang;
  if(this.language!==language){
   this.language=language;
   this.root.querySelectorAll('[data-pl]').forEach(node=>{node.textContent=tr(node.dataset.pl,node.dataset.en);});
  }
  const state=this.safety.state,height=state?.actuators?.height?.value,balance=state?.actuators?.balance?.enabled;
  if(!this.dirty.has('height') && document.activeElement!==this.height && Number.isInteger(height)){this.height.value=height;this.root.querySelector('output').textContent=String(height);}
  if(!this.dirty.has('balance') && document.activeElement!==this.balance)this.balance.value=typeof balance==='boolean'?(balance?'1':'0'):'';
  for(const action of ['height','balance','action']){
   const allowed=!this.busy && this.safety.can('manual',action);
   this.root.querySelector('#posture-'+action+'-send').disabled=!allowed;
   this.root.querySelector('#posture-'+action).disabled=!allowed;
  }
  this.root.querySelector('#posture-state').textContent=tr('Ostatnie polecenie: wysokość ','Last command: height ')+(height??'—')+tr(' · balans ',' · balance ')+(typeof balance==='boolean'?(balance?tr('włączony','on'):tr('wyłączony','off')):'—')+tr('. Suwak wysyła po puszczeniu. Nastawy, nie pomiary.','. The slider sends on release. Settings, not measurements.');
  this.root.querySelector('#posture-action-status').textContent=state?.capabilities?.action?.available?tr('Figury zmieniają postawę robota.','Figures change the robot posture.'):tr('Figury dostępne w SDK; wykonanie zablokowane do potwierdzenia możliwości ich przerwania.','Figures are available in the SDK; execution is blocked until interruption is verified.');
 }
}
