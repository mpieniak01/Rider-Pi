#!/usr/bin/env python3
import os, time, json, zmq, pygame
os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

SUB_ADDR   = os.getenv("BUS_SUB_ADDR", "tcp://127.0.0.1:5556")
MOTION_T   = os.getenv("MOTION_STATE_TOPIC", "motion.state").encode()
VISION_T   = os.getenv("VISION_TOPIC", "vision.state").encode()
CTRL_T     = os.getenv("UI_CTRL_TOPIC", "ui.control").encode()
FPS        = float(os.getenv("UI_FPS", "15"))

def make_sub():
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.SUB)
    s.connect(SUB_ADDR)
    for t in (MOTION_T, VISION_T, CTRL_T):
        s.setsockopt(zmq.SUBSCRIBE, t)
    poll = zmq.Poller()
    poll.register(s, zmq.POLLIN)
    return s, poll

def main():
    pygame.display.init()
    pygame.font.init()
    screen = pygame.display.set_mode((0,0), pygame.FULLSCREEN)
    font = pygame.font.SysFont(None, 26)

    sub, poll = make_sub()
    state = {"motion": {}, "vision": {}}
    draw_enabled = True

    clock = pygame.time.Clock()
    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                running = False

        socks = dict(poll.poll(timeout=0))
        if sub in socks and socks[sub] == zmq.POLLIN:
            topic, payload = sub.recv_multipart()
            if topic == CTRL_T:
                msg = json.loads(payload.decode("utf-8"))
                draw_enabled = bool(msg.get("draw", True))
            elif topic == MOTION_T:
                state["motion"] = json.loads(payload.decode("utf-8"))
            elif topic == VISION_T:
                state["vision"] = json.loads(payload.decode("utf-8"))

        if draw_enabled:
            screen.fill((0,0,0))
            lines = []
            m = state.get("motion", {})
            v = state.get("vision", {})
            lines.append(f"MOTION: en={m.get('enabled')} estop={m.get('estop')} stopped={m.get('stopped')}")
            out = m.get("output", {})
            lines.append(f"OUT: lx={out.get('lx',0):.2f} az={out.get('az',0):.2f}")
            lines.append(f"WD: {m.get('last_cmd_age_ms',0)}ms / {m.get('watchdog_ms',0)}ms")
            lines.append(f"VISION: moving={v.get('moving')} human={v.get('human', False)} motion={v.get('motion',0):.1f}")

            y = 20
            for s in lines:
                img = font.render(s, False, (200, 200, 200))
                screen.blit(img, (20, y))
                y += 28
            pygame.display.flip()
            clock.tick(FPS)
        else:
            time.sleep(0.05)

    pygame.quit()

if __name__ == "__main__":
    main()