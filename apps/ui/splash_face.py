# apps/ui/splash_face.py
#!/usr/bin/env python3
import os, time, socket, pygame

# (opcjonalnie) sysinfo z lokalnego API
def get_battery_pct():
    try:
        import requests  # python3-requests jest zainstalowany
        r = requests.get("http://127.0.0.1:8080/sysinfo", timeout=0.4)
        if r.ok:
            return r.json().get("battery_pct")
    except Exception:
        pass
    return None

def get_ip():
    try:
        host = socket.gethostname()
        ips = socket.gethostbyname_ex(host)[2]
        for ip in ips:
            if not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return "0.0.0.0"

def main():
    fbdev = os.environ.get("FBDEV", "/dev/fb1")
    rot = int(os.environ.get("ROT", "0"))           # 0/90/180/270
    secs = float(os.environ.get("SPLASH_SECS", "3"))

    # SDL -> framebuffer
    os.environ["SDL_VIDEODRIVER"] = "fbcon"
    os.environ["SDL_FBDEV"] = fbdev
    os.environ["SDL_NOMOUSE"] = "1"

    pygame.init()
    pygame.mouse.set_visible(False)
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    w, h = screen.get_size()

    # Rysowanie na osobnym buforze
    surf = pygame.Surface((w, h))
    surf.fill((0, 0, 0))

    # --- Buźka ---
    cx, cy = w // 2, h // 2
    r = min(w, h) // 4
    pygame.draw.circle(surf, (255, 215, 0), (cx, cy), r)                 # twarz
    pygame.draw.circle(surf, (0, 0, 0), (cx - r // 3, cy - r // 3), r // 10)  # lewe oko
    pygame.draw.circle(surf, (0, 0, 0), (cx + r // 3, cy - r // 3), r // 10)  # prawe oko
    pygame.draw.arc(surf, (0, 0, 0), (cx - r // 2, cy - r // 6, r, r), 3.5, 5.9, 5)  # uśmiech

    # --- Tekst: hostname / IP / bateria ---
    font = pygame.font.SysFont("DejaVu Sans", 18)  # mamy fonts-dejavu
    lines = [
        f"{socket.gethostname()} • {get_ip()}",
    ]
    bat = get_battery_pct()
    if bat is not None:
        lines.append(f"Battery: {bat}%")

    y = 10
    for line in lines:
        txt = font.render(line, True, (230, 230, 230))
        surf.blit(txt, (10, y))
        y += txt.get_height() + 4

    # Rotacja (jeśli 90/270 — przeskaluj z powrotem do ekranu)
    if rot in (90, 180, 270):
        rotated = pygame.transform.rotate(surf, -rot)
        if rot in (90, 270):
            rotated = pygame.transform.smoothscale(rotated, (w, h))
        surf = rotated

    screen.blit(surf, (0, 0))
    pygame.display.update()
    time.sleep(secs)
    pygame.quit()

if __name__ == "__main__":
    main()
