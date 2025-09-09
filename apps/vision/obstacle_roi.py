#!/usr/bin/env python3
# apps/vision/obstacle_roi.py
import os, time, json
import zmq

BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
ZPUB = f"tcp://127.0.0.1:{BUS_PUB_PORT}"
ZSUB = f"tcp://127.0.0.1:{BUS_SUB_PORT}"

ROI_Y = float(os.getenv("OBST_ROI_Y", "0.65"))           # dolny pas od 65% wysokości
MIN_W_FR = float(os.getenv("OBST_MIN_W_FRAC", "0.18"))   # min szerokość bbox / W
MIN_A_FR = float(os.getenv("OBST_MIN_AREA_FRAC", "0.06"))# min pole bbox / (W*H)
CLS_RAW = os.getenv("OBST_CLASSES", "*").strip()
CLASSES = None if CLS_RAW in ("*", "", "all") else {c.strip().lower() for c in CLS_RAW.split(",")}
ON_CONSEC = int(os.getenv("OBST_ON_CONSEC", "2"))
OFF_TTL   = float(os.getenv("OBST_OFF_TTL", "0.7"))

def zmq_pub():
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.PUB); s.connect(ZPUB)
    return s

def zmq_sub():
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.SUB); s.connect(ZSUB)
    s.setsockopt_string(zmq.SUBSCRIBE, "vision.detections")
    return s

def parse_msg(msg):
    # "topic {json}"
    sp = msg.find(" ")
    if sp <= 0: return None, None
    topic = msg[:sp]; payload = json.loads(msg[sp+1:])
    return topic, payload

def intersects_roi(b, W, H):
    x,y,w,h = b
    yb = y + h
    roi_y = int(ROI_Y * H)
    if yb < roi_y: return False
    area = (w*h)/(W*H)
    if (w/float(W) >= MIN_W_FR) or (area >= MIN_A_FR):
        return True
    return False

def main():
    sub = zmq_sub()
    pub = zmq_pub()
    present = False
    pos_streak = 0
    last_pos_ts = 0.0

    while True:
        try:
            msg = sub.recv_string(flags=zmq.NOBLOCK)
        except zmq.Again:
            # timeout / tick off-ttl
            if present and (time.time() - last_pos_ts > OFF_TTL):
                present = False
                pub.send_string("obstacle.state " + json.dumps({
                    "front": False, "ts": time.time(), "reason": "ttl"
                }))
            time.sleep(0.02)
            continue

        _, payload = parse_msg(msg)
        if not payload: continue
        W, H = payload.get("size", [0,0])
        items = payload.get("items", [])

        hit = False
        nearest = None
        for it in items:
            name = str(it.get("name","")).lower()
            if CLASSES and name not in CLASSES: 
                continue
            if float(it.get("score",0.0)) < float(os.getenv("VISION_MIN_SCORE","0.5")):
                continue
            bbox = it.get("bbox",[0,0,0,0])
            if intersects_roi(bbox, W, H):
                hit = True
                # keep biggest area as "nearest"
                area = bbox[2]*bbox[3]
                if not nearest or area > nearest[0]:
                    nearest = (area, name, bbox)

        if hit:
            pos_streak += 1
            last_pos_ts = time.time()
            if not present and pos_streak >= ON_CONSEC:
                present = True
                pub.send_string("obstacle.state " + json.dumps({
                    "front": True, "ts": time.time(),
                    "reason": "bbox_roi",
                    "nearest": {"name": nearest[1], "bbox": nearest[2]} if nearest else None
                }))
        else:
            pos_streak = 0
            if present and (time.time() - last_pos_ts > OFF_TTL):
                present = False
                pub.send_string("obstacle.state " + json.dumps({
                    "front": False, "ts": time.time(), "reason": "clear"
                }))

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: pass
