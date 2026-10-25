# Turning the camera source off

Both panels use `POST /api/resource/camera/pipeline` with action=stop.
OFF applies to the image source, not just a preview or panel task.

After an API restart, capture may still run without a restored goal. Explicit
OFF recovers that source only when fresh producer status (PID, profile, revision
and session) matches the exact systemd group of one active
`camera-capture@raw/edge/ssd.service`. Stopping uses the existing service
administration layer and its lock. Missing ownership evidence, another consumer
or concurrent sources still cause refusal. Changing a profile never takes over
a source.

Confirmation requires both stopped service and producer status; a positive
systemd backend response alone is insufficient. Repeating the same request
returns its recorded result without stopping a newer session. Existing motion
guards and automation-generation invalidation remain in force. OFF never arms.

Device acceptance checks OFF in Pi and Venom panels, no capture process, released
camera ownership, no new frames and retained OFF after refresh. Software tests
use only mocked services in WSL/CI. [Camera pipeline](../CAMERA_PIPELINE_V1.md).
