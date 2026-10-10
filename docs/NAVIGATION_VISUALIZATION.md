# Navigation view

The current /navigation view uses the shared operator panel, existing /events
SSE stream and GET /api/navigator/status. It requires no additional daemon,
port, WebSocket or environment switch.

The API presentation cache observes robot.pose, mapper.map.data and
navigator.path through its existing BUS subscriber. GET only reads that
cache. It never requests mapping, starts a task or drives the robot.
Producer timestamps remain unchanged; missing data stays unknown.
Map data is bounded to 65,536 cells, path data to 2,000 points.
World coordinates use the mapper's additive origin offset.

The canvas displays obstacles, free/unknown cells, pose, and a path/target
when the producer supplies them. It does not fabricate a pose or route.
Map age and quality are shown separately from pose/path. Map observations
older than 10 seconds and pose/path older than 3 seconds are dimmed.
SSE updates real data; periodic reads cover missed stream updates.

Explicit start/return-home requests require current navigation permission
and one original generation/sequence/timestamp envelope. HTTP 202 remains
pending. Configuration is available only in DISARMED. SDK acknowledgement
does not confirm physical completion. Prepare consent in this same view:
leaving the view attempts STOP and revokes local permission.

The optional legacy /ws/navigation integration remains disabled by default.
RIDER_NAV_VISUALIZER_ENABLED controls that separate compatibility service;
it is not required by the current panel.

See the [operator panel](ui/operator-panel.md) for the complete contract and
loopback fixture verification. No automatic test authorizes physical motion.
