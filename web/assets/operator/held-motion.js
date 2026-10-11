// One request in flight, one latest intent. Never replay a backlog of directions.
export class HeldMotion {
  constructor({send, modes, allowed, error, active, now=()=>Date.now(),
    timer=(fn,ms)=>setTimeout(fn,ms), cancel=id=>clearTimeout(id)}) {
    Object.assign(this,{send,modes,allowed,error,active,now,timer,cancel});
    this.epoch=0;this.gesture=null;this.pending=null;this.flight=false;
  }
  begin(direction, identity) {
    if(!this.allowed(direction))return;
    const continuing=this.gesture?.holding===true;
    this.cancel(this.delay);this.cancel(this.renew);
    const epoch=++this.epoch;
    this.gesture={direction,identity,epoch,holding:continuing};
    this.active(direction);
    if(continuing){this.offer({direction,mode:"hold",epoch});return;}
    this.delay=this.timer(()=>{
      if(this.gesture?.epoch!==epoch)return;
      this.gesture.holding=true;
      this.offer({direction,mode:'hold',epoch});
    },this.modes().click_threshold_ms);
  }
  end(identity, cancelled=false) {
    const g=this.gesture;
    if(!g || identity!==undefined && identity!==g.identity)return;
    this.gesture=null;this.cancel(this.delay);this.cancel(this.renew);
    const epoch=++this.epoch;
    this.active(null);
    this.pending=null;
    if(g.holding)this.offer({direction:g.direction,mode:'release',epoch});
    else if(!cancelled)this.offer({direction:g.direction,mode:'pulse',epoch});
  }
  stop() {
    this.gesture=null;this.pending=null;++this.epoch;
    this.cancel(this.delay);this.cancel(this.renew);this.active(null);
  }
  click(direction) {
    if(this.allowed(direction)) {
      this.stop();this.offer({direction,mode:'pulse',epoch:this.epoch});
    }
  }
  valid(intent) { return intent.epoch===this.epoch && (intent.mode!=='hold' || this.gesture?.holding===true); }
  offer(intent) {
    this.pending=intent;
    if(!this.flight)this.flush();
  }
  async flush() {
    const intent=this.pending;if(!intent)return;
    this.pending=null;this.flight=true;const started=this.now();
    try {
      await this.send(intent,()=>this.valid(intent));
    } catch(error) {
      if(this.valid(intent)){this.stop();this.error(error);}
    } finally {
      this.flight=false;
      if(this.pending)this.flush();
      else if(this.valid(intent) && intent.mode==='hold') {
        this.renew=this.timer(()=>{
          if(this.valid(intent))this.offer(intent);
        },Math.max(0,this.modes().hold_renewal_ms-(this.now()-started)));
      }
    }
  }
}
