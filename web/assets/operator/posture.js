import { tr, showError } from './ui.js';
export class Posture {
 constructor(safety) {
  this.dirty = new Set();
  this.safety=safety;this.root=document.getElementById('posture-controls');
  this.root.innerHTML='<h2>Postawa robota</h2><div class="posture-row"><label for="posture-height">↕ Wysokość</label><span>Niżej</span><input id="posture-height" type="range" min="75" max="115" step="1" value="90" disabled><span>Wyżej</span><output>90</output><button class="c-btn" id="posture-height-send" type="button">Ustaw</button></div><div class="posture-row"><label for="posture-balance">Balansowanie przechyłu</label><select id="posture-balance" disabled><option value="">Wybierz</option><option value="1">Włączone</option><option value="0">Wyłączone</option></select><button class="c-btn" id="posture-balance-send" type="button">Ustaw</button></div><p class="operator-muted" id="posture-state"></p><details><summary>Figury producenta</summary><div class="posture-row"><select id="posture-action"><option value="1">Kołysanie</option><option value="2">Ruch pionowy</option><option value="5">Podniesienie i obrót</option><option value="6">Ruch okrężny</option><option value="255">Pozycja domyślna / reset</option></select><button class="c-btn" id="posture-action-send" type="button">Wykonaj</button></div><p id="posture-action-status" class="operator-muted"></p></details>';
  this.height=this.root.querySelector('#posture-height');this.balance=this.root.querySelector('#posture-balance');
  this.height.oninput=()=>{this.dirty.add('height');this.root.querySelector('output').textContent=this.height.value;};
  this.balance.onchange=()=>this.dirty.add('balance');
  this.height.onchange=()=>this.send('height',{height:Number(this.height.value)});
  this.root.querySelector('#posture-height-send').onclick=()=>this.send('height',{height:Number(this.height.value)});
  this.root.querySelector('#posture-balance-send').onclick=()=>{if(this.balance.value!=='')this.send('balance',{enabled:this.balance.value==='1'});};
  this.root.querySelector('#posture-action-send').onclick=()=>this.send('action',{action_id:Number(this.root.querySelector('#posture-action').value)});
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
  const state=this.safety.state,height=state?.actuators?.height?.value,balance=state?.actuators?.balance?.enabled;
  if(!this.dirty.has('height') && document.activeElement!==this.height && Number.isInteger(height)){this.height.value=height;this.root.querySelector('output').textContent=String(height);}
  if(!this.dirty.has('balance') && document.activeElement!==this.balance)this.balance.value=typeof balance==='boolean'?(balance?'1':'0'):'';
  for(const action of ['height','balance','action']){
   const allowed=!this.busy && this.safety.can('manual',action);
   this.root.querySelector('#posture-'+action+'-send').disabled=!allowed;
   this.root.querySelector('#posture-'+action).disabled=!allowed;
  }
  this.root.querySelector('#posture-state').textContent='Ostatnie polecenie: wysokość '+(height??'—')+' · balans '+(typeof balance==='boolean'?(balance?'włączony':'wyłączony'):'—')+'. Suwak wysyła po puszczeniu. Nastawy, nie pomiary.';
  this.root.querySelector('#posture-action-status').textContent=state?.capabilities?.action?.available?'Figury zmieniają postawę robota.':'Figury dostępne w SDK; wykonanie zablokowane do potwierdzenia możliwości ich przerwania.';
 }
}
