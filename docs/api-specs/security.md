# HTTP and runtime file security

The shared guard runs before handlers in the main API, compatibility app,
motion bridge and both voice workers. It does not start services or change
operator consent, command generations, TTL or STOP semantics.

## Origin and content type

Browsers may use the server's own origin by default. Explicitly configure any
additional origins in comma-separated `RIDER_ALLOWED_ORIGINS`, for example
`http://localhost:3300,https://venom.example:8443`. Scheme, host and port must
match; default HTTP/HTTPS ports are normalized. Wildcards, paths and `null`
are unsupported. A foreign or malformed request `Origin` returns HTTP 403
before the handler runs, including preflight. Allowed responses reflect the
specific origin, add `Vary: Origin` and do not enable cross-origin cookies.

CLI and server clients without `Origin` remain supported. Mutations carrying
`Sec-Fetch-Site: cross-site` or `same-site` without `Origin` are rejected.
Keep the API off untrusted networks: this boundary restricts browser requests;
it does not authenticate clients. Agent and playback bearer authorization
remain separate. Host names require local/operator trust before they can define the same-origin
boundary. Arbitrary matching Host/Origin pairs are rejected to prevent DNS rebinding. Behind a TLS proxy,
explicitly add the public HTTPS origin; the app does not automatically trust
`X-Forwarded-Host`.

Nonempty `POST`, `PUT`, `PATCH` and `DELETE` bodies require JSON
(`application/json` or `application/*+json`), otherwise HTTP 415
`unsupported_content_type` is returned. Empty requests remain supported,
including OAuth initialization and STOP. Unknown stream lengths cannot bypass
the check: at most one byte is inspected for a non-JSON request before a
nonempty body is rejected.

Existing binary upload exceptions are `/api/compute/tasks/<task>`,
`/api/voice/playback`, `/api/voice/asr` and the voice worker's `/api/asr`.
Their handlers still enforce format, input limits and authentication.
Origin checks also apply to uploads. `/api/voice/playback/cancel` requires JSON.

## Face PNG export

`/face/render`, `/api/draw/face` and `/draw/face` share the same restrictions.
`out` accepts `face.png` or `face_<name>.png`, with 1–100 ASCII letters,
digits, hyphens or underscores in the name. An absolute path with that basename
directly under `FACE_RENDER_DIR` (default `/tmp`) is also allowed. Subdirectories,
`..`, other extensions and other directories return HTTP 400
`invalid_face_output`. Examples: `face_api.png`, `/tmp/face_api_test.png`.
The directory is operator configuration, never request-supplied configuration.

Writes use an open directory descriptor, a random temporary filename,
`O_EXCL`, `O_NOFOLLOW` and atomic replacement. Output permissions are `0600`;
replacing a symlink or hardlink never modifies its linked target. The directory
must belong to the process user or root, must have no symlink in any directory component, and must not
be writable by others without the sticky bit. Prefer an operator-owned private
directory for new configurations. Access failures return HTTP 503
`face_export_unavailable`. Existing PNG entries in this scope may be replaced.

Size is bounded to 16–1024 and rotation to 0/90/180/270 before rendering;
invalid input returns HTTP 400 `invalid_face_preview`. `Accept: image/png`
without `out` returns an in-memory preview. Explicit null or empty `out`
values do not bypass export validation.

## Provider change reason

Optional `reason` for domain/PC-address changes must be nonblank printable text
of at most 256 characters. Control characters, newlines and non-string values
return HTTP 400 `invalid_provider_reason` before persistence or BUS publication.
A missing field defaults to `manual`; an explicit empty value does not.
Logging additionally uses a quoted representation.

## Runtime files and owner locks

The legacy animation `FileSink` writes snapshots through a random `0600` file
and atomic replacement, as PNG exports do. It no longer opens a predictable
`face_latest.tmp`. Every directory component is opened without following
symlinks and checked for ownership and write permissions. Output names and
`FACE_LATEST_PATH` / `FACE_LEGACY_PATH` remain supported; file consumers need
permission to read the `0600` output.

PID and UART-owner locks keep their existing paths but accept only regular files
owned by the process user, with a single link and no group/other write access.
Symlinks, hardlinks and foreign-owned files are rejected before PID writes or
SDK construction. Valid existing files are restricted to `0600`; the PID is
updated only after acquiring the lock. UART inventory and the safety gate
remain enforced.

Lock files remain after process shutdown so that the next owner uses the same
inode. File existence or a recorded PID alone does not prove active ownership.
Do not remove or replace a lock file while any process using it is running.
Process termination releases the operating-system lock.

## Optional voice recordings

`save_audio` remains disabled by default. When enabled, the recording directory
must belong to the service user and have `0700` permissions; new directories
are created with those permissions. Existing directories accessible to a group
or other users are rejected. Operators should prepare a dedicated private
directory first; the service does not automatically change permissions on the
configured directory or old recordings.

WAV files receive random names and `0600` permissions and are published only
after writing completes. A filename collision never overwrites a previous
recording. File and directory permissions remain private under a permissive
process `umask`. Audio capture behavior and format remain unchanged.

## Persistent state and command cache

LED generations (`RIDER_LED_STATE_PATH`), feature state (`FEATURE_STATE_PATH`)
and the last Google command (`DATA_DIR/google/last_command.json`) use the same
anchored atomic writer. Each directory component is checked without following
symlinks; a random exclusive temporary file is published only after writing
finishes. Existing target symlinks and hardlinks are replaced without modifying
their linked files. Failed writes preserve the previous published contents.

New files are private (`0600`) and newly created directories use `0700`.
Existing trusted directories retain their permissions, including the shared
`/run/rider-motion` directory (`0750`). Readers must run as the writing service
user or root. Prepare paths as that service user; do not use symlinked directories.
JSON values, including text containing `../`, remain data and never choose the
output path. The configured paths remain operator settings.

Feature persistence still returns failure before a movement producer can start
without its accepted generation. LED persistence failures remain unconfirmed
journal errors; command-cache failures remain nonfatal warnings. Concurrent
writers publish complete files independently; this does not add transaction or
merge semantics for simultaneous state updates.

## Host, provider and CLI boundaries

Private numeric addresses, loopback and the device hostname (including `.local`)
remain usable for the local panel. Additional proxy names require explicit
`RIDER_TRUSTED_HOSTS` or a host from `RIDER_ALLOWED_ORIGINS`. The request Host
never creates its own trust entry. Rejected hosts return `host_not_allowed`.
Remote provider URLs require HTTPS; loopback HTTP remains available for local
workers and SSH tunnels. Credentials, control characters and ambiguous URLs are
rejected. Migrate stored non-loopback HTTP addresses to HTTPS or an encrypted
loopback tunnel before using them.

Agent-invoked compute/UART export tools confine output to the invocation directory,
resolve links before checking containment and never overwrite an existing result.
Run them from the intended data directory. Diagnostic HTTP targets and ports use
`RIDER_DIAGNOSTIC_HOSTS` (default loopback names/addresses) and
`RIDER_DIAGNOSTIC_PORTS` (8080,8081,443); redirects and implicit proxies are disabled.
Prepare any LAN device host explicitly in operator configuration.

LCD ownership accepts only a regular, single-link, non-publicly-writable lock,
opened through checked directory descriptors. Root boot and the pi service can
share the existing readonly lock; descriptors and the stable inode remain the
ownership mechanism. The lock contains no credentials.
