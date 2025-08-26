cd ~/robot
mkdir -p systemd
cat > systemd/rider-menu.service <<'EOF'
[Unit]
Description=Rider-Pi Menu (CLI)
After=rider-broker.service rider-motion.service
Wants=rider-broker.service rider-motion.service

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/home/pi/robot
Environment=BUS_PUB_ADDR=tcp://127.0.0.1:5555
Environment=MOTION_TOPIC=motion
ExecStart=/usr/bin/python3 -u /home/pi/robot/apps/menu/main.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
