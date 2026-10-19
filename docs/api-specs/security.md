# HTTP boundary and PNG exports

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
remain separate. Comparing against the request host does not replace DNS
rebinding protection or trusted host/proxy configuration. Behind a TLS proxy,
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
must belong to the process user or root, must not be a symlink, and must not
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
