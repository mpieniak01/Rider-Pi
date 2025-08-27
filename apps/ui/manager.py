#!/usr/bin/env python3
import os, time, json, subprocess, zmq, re
try:
    from PIL import Image
except Exception:
    Image = None

SUB_ADDR=os.getenv("BUS_SUB_ADDR","tcp://127.0.0.1:5556")
PUB_ADDR=os.getenv("BUS_PUB_ADDR","tcp://127.0.0.1:5555")
MOTION_T=os.getenv("MOTION_STATE_TOPIC","motion.state").encode()
VISION_T=os.getenv("VISION_TOPIC","vision.state").encode()
CTRL_T  =os.getenv("UI_CTRL_TOPIC","ui.control").encode()

CHAT_MODE=int(os.getenv("UI_CHAT_MODE","1"))
DIM_SEC  =float(os.getenv("UI_INACTIVITY_DIM_SEC","30"))
OFF_SEC  =float(os.getenv("UI_INACTIVITY_OFF_SEC","120"))
DIM_MODE =os.getenv("UI_DIM_MODE","xgo").strip().lower()
AUDIO_HOOK=os.getenv("UI_AUDIO_HOOK","/home/pi/robot/apps/ui/volume_hooks.sh")
XGO_DIM   =int(os.getenv("UI_XGO_DIM","10"))
XGO_BRIGHT=int(os.getenv("UI_XGO_BRIGHT","80"))
XGO_BLACK =int(os.getenv("UI_XGO_BLACK_DIM","0"))==1

def log(m): print(f"[ui] {m}", flush=True)

class DisplayCtl:
    def __init__(self, mode:str):
        self.mode=mode; self._power=1
        self._xgo_lcd=None; self._xgo_size=None
        self._set_bl=None;  self._gpio_pwm=None
        if self.mode=="xgo":
            try:
                import xgoscreen.LCD_2inch as LCD_2inch
                self._mod=LCD_2inch
                lcd=LCD_2inch.LCD_2inch(); lcd.Init()
                self._xgo_lcd=lcd
                w=int(getattr(lcd,"height",240)); h=int(getattr(lcd,"width",320))
                self._xgo_size=(w,h)
                # znajdź setter BL
                self._set_bl=self._find_callable(lcd,[
                    r"^bl[_]?DutyCycle$",r"^BL[_]?DutyCycle$",r"set[_]?backlight",
                    r"^SetBL$",r"^setBL$",r"^bl[_]?Value$",r"^BLValue$",
                ],"BL")
                if self._set_bl: log("xgo: użyję BL via bl_DutyCycle (lub ekwiwalent)")
                # spróbuj ustawić jasność; jeśli padnie na _pwm → zrób autoinit GPIO
                if self._set_bl and not self._bl_set_safe(XGO_BRIGHT, try_gpio_init=True):
                    log("xgo: BL wstępnie się nie udał (nawet po init) — przełączę na czarną klatkę jako fallback")
            except Exception as e:
                log(f"xgo: init fail: {e}"); self.mode="none"

    def _find_callable(self,obj,patterns,label):
        for n in dir(obj):
            try: fn=getattr(obj,n)
            except Exception: continue
            if callable(fn):
                ln=n.lower()
                if any(re.search(p,n) or re.search(p,ln) for p in patterns):
                    log(f"xgo: znaleziono {label}: {n}"); return fn
        return None

    def _ensure_gpio_pwm(self):
        if self._gpio_pwm: return True
        try:
            lcd=self._xgo_lcd
            bl_pin = getattr(lcd,"BL_PIN", None)
            freq   = int(getattr(lcd,"BL_freq", 1000))
            if bl_pin is None: 
                log("xgo: nie znaleziono BL_PIN na instancji"); return False
            import RPi.GPIO as GPIO
            GPIO.setwarnings(False); GPIO.setmode(GPIO.BCM)
            GPIO.setup(bl_pin, GPIO.OUT)
            pwm=GPIO.PWM(bl_pin, freq); pwm.start(max(0,min(100,XGO_BRIGHT)))
            self._gpio_pwm=pwm
            try: setattr(lcd,"_pwm", pwm)
            except Exception: pass
            log(f"xgo: GPIO PWM init (pin={bl_pin}, freq={freq} Hz)")
            return True
        except Exception as e:
            log(f"xgo: GPIO PWM init err: {e}")
            return False

    def _bl_set_safe(self, value:int, try_gpio_init=False):
        if not self._set_bl: return False
        value=max(0,min(100,int(value)))
        try:
            self._set_bl(value); return True
        except Exception as e:
            if ("_pwm" in str(e) or "PWM" in str(e)) and try_gpio_init:
                if self._ensure_gpio_pwm():
                    try: self._set_bl(value); return True
                    except Exception as e2: log(f"xgo: BL retry err: {e2}")
            else:
                log(f"xgo: BL set err: {e}")
            return False

    def dim(self)->bool:
        if self.mode=="xgo" and self._xgo_lcd is not None:
            if self._set_bl and self._bl_set_safe(XGO_DIM, try_gpio_init=True):
                log(f"xgo: DIM -> {XGO_DIM}%"); return True
            if XGO_BLACK and Image and self._xgo_size:
                try:
                    from PIL import Image as _I
                    img=_I.new("RGB", self._xgo_size,(0,0,0))
                    self._xgo_lcd.ShowImage(img); log("xgo: DIM -> czarna klatka"); return True
                except Exception as e: log(f"xgo: black DIM err: {e}")
        return False

    def undim(self):
        if self.mode=="xgo" and self._xgo_lcd is not None and self._set_bl:
            if self._bl_set_safe(XGO_BRIGHT, try_gpio_init=True):
                log(f"xgo: UNDIM -> {XGO_BRIGHT}%")

    def set_power(self,on:bool):
        state=1 if on else 0
        if self._power==state: return
        ok=False
        if self.mode=="xgo" and self._xgo_lcd is not None:
            if self._set_bl:
                ok=self._bl_set_safe(XGO_BRIGHT if on else 0, try_gpio_init=True)
                log(f"xgo: POWER -> {'ON' if on else 'OFF'} ({XGO_BRIGHT if on else 0}%)")
            else:
                if not on and Image and self._xgo_size:
                    try:
                        from PIL import Image as _I
                        img=_I.new("RGB", self._xgo_size,(0,0,0))
                        self._xgo_lcd.ShowImage(img); ok=True; log("xgo: POWER OFF -> czarna klatka")
                    except Exception as e: log(f"xgo: black OFF err: {e}")
        elif self.mode=="vcgencmd":
            ok=self._run(["/usr/bin/vcgencmd","display_power",str(state)])
        elif self.mode=="fb":
            try:
                with open("/sys/class/graphics/fb0/blank","w") as f: f.write("0" if on else "1")
                ok=True
            except Exception as e: log(f"fb: POWER err: {e}")
        if ok: self._power=state

    def _run(self,cmd): 
        try: subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False); return True
        except Exception: return False

    def ensure_on(self):
        self.set_power(True)
        if self.mode=="xgo": self.undim()

def make_pub():
    ctx=zmq.Context.instance()
    s=ctx.socket(zmq.PUB); s.connect(PUB_ADDR); time.sleep(0.1); return s

def make_sub():
    ctx=zmq.Context.instance()
    s=ctx.socket(zmq.SUB); s.connect(SUB_ADDR)
    s.setsockopt(zmq.SUBSCRIBE,MOTION_T); s.setsockopt(zmq.SUBSCRIBE,VISION_T)
    poll=zmq.Poller(); poll.register(s,zmq.POLLIN); return s,poll

def audio_hook(evt:str):
    try:
        hook=AUDIO_HOOK
        if os.path.isfile(hook) and os.access(hook,os.X_OK):
            subprocess.Popen([hook,evt],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except Exception: pass

def main():
    log(f"start: mode={DIM_MODE} dim={DIM_SEC}s off={OFF_SEC}s chat={CHAT_MODE}")
    disp=DisplayCtl(DIM_MODE); pub=make_pub(); sub,poll=make_sub()
    draw_enabled=True; last_activity=time.time(); dimmed=False; powered_off=False
    def set_draw(en:bool):
        nonlocal draw_enabled
        if en==draw_enabled: return
        draw_enabled=en; pub.send_multipart([CTRL_T, json.dumps({'draw':bool(en)}).encode('utf-8')])
        log(f"ui.control -> draw={en}")
    disp.ensure_on(); set_draw(True)
    motion_stopped=True; vision_moving=False; vision_human=False
    while True:
        socks=dict(poll.poll(timeout=200))
        if sub in socks and socks[sub]==zmq.POLLIN:
            topic,payload=sub.recv_multipart(); data=json.loads(payload.decode("utf-8"))
            if topic==MOTION_T:
                motion_stopped=bool(data.get("stopped",True))
                age=int(data.get("last_cmd_age_ms",9999))
                if age<500 or not motion_stopped: last_activity=time.time()
            elif topic==VISION_T:
                vision_moving=bool(data.get("moving",False))
                vision_human =bool(data.get("human",False))
                if vision_moving or vision_human: last_activity=time.time()
        if not motion_stopped: set_draw(False)
        else: set_draw((CHAT_MODE==1) and (vision_human or vision_moving))
        idle=time.time()-last_activity
        if idle>OFF_SEC and not powered_off:
            disp.set_power(False); powered_off=True; dimmed=True; audio_hook("off"); log("OFF")
        elif idle>DIM_SEC and not dimmed:
            if not disp.dim(): audio_hook("dim")
            dimmed=True; log("DIM")
        elif idle<=DIM_SEC and (dimmed or powered_off):
            disp.ensure_on(); dimmed=False; powered_off=False; audio_hook("on"); log("ON")

if __name__=="__main__": main()