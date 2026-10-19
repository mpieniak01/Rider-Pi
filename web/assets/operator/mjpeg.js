// Generated from venom-module-rider web-next/lib/mjpeg.ts; shared wire parser v1.
const MAX_IMAGE = 2 * 1024 * 1024, MAX_HEADERS = 16 * 1024;
const encoder = new TextEncoder(), decoder = new TextDecoder("utf-8", { fatal: true });
function at(bytes, value, start = 0) {
    outer: for (let i = start; i <= bytes.length - value.length; i++) {
        for (let j = 0; j < value.length; j++)
            if (bytes[i + j] !== value[j])
                continue outer;
        return i;
    }
    return -1;
}
export class MjpegParser {
    constructor(contentType) {
        this.buffer = new Uint8Array();
        this.ended = false;
        this.trailer = 0;
        if (!/^multipart\/x-mixed-replace\s*;/i.test(contentType))
            throw new Error("stream_content_type");
        const match = /(?:^|;)\s*boundary=(?:"([^"]+)"|([^;\s]+))/i.exec(contentType);
        const boundary = match?.[1] ?? match?.[2] ?? "";
        if (!/^[A-Za-z0-9'()+_,./:=?-]{1,120}$/.test(boundary))
            throw new Error("stream_boundary");
        this.marker = encoder.encode("--" + boundary);
    }
    feed(chunk) {
        if (this.ended) {
            this.ending(chunk);
            return [];
        }
        const parts = [];
        // Fetch may return a large coalesced chunk. Slice it to keep the parser's own
        // storage bounded even before inspecting Content-Length.
        for (let offset = 0; offset < chunk.length; offset += 65536) {
            const piece = chunk.subarray(offset, offset + 65536);
            const joined = new Uint8Array(this.buffer.length + piece.length);
            joined.set(this.buffer);
            joined.set(piece, this.buffer.length);
            this.buffer = joined;
            this.parse(parts);
            if (this.buffer.length > MAX_IMAGE + MAX_HEADERS + 256)
                throw new Error("stream_buffer_limit");
        }
        return parts;
    }
    readBoundary() {
        if (this.buffer.length >= 2 && this.buffer[0] === 13 && this.buffer[1] === 10)
            this.buffer = this.buffer.subarray(2);
        if (this.buffer.length < this.marker.length + 2)
            return false;
        if (at(this.buffer, this.marker) !== 0)
            throw new Error("stream_part_boundary");
        const tail = this.marker.length;
        if (this.buffer[tail] === 45 && this.buffer[tail + 1] === 45) {
            this.ended = true;
            this.ending(this.buffer.subarray(tail + 2));
            this.buffer = new Uint8Array();
            return false;
        }
        if (this.buffer[tail] !== 13 || this.buffer[tail + 1] !== 10)
            throw new Error("stream_part_boundary");
        return true;
    }
    readHeaders() {
        const tail = this.marker.length;
        const end = at(this.buffer, encoder.encode("\r\n\r\n"), tail + 2);
        if (end < 0) {
            if (this.buffer.length > MAX_HEADERS)
                throw new Error("stream_headers_limit");
            return null;
        }
        if (end > MAX_HEADERS)
            throw new Error("stream_headers_limit");
        const headers = new Headers();
        for (const line of decoder.decode(this.buffer.subarray(tail + 2, end)).split("\r\n")) {
            const colon = line.indexOf(":");
            if (colon < 1)
                throw new Error("stream_header");
            const name = line.slice(0, colon).trim(), value = line.slice(colon + 1).trim();
            if (headers.has(name))
                throw new Error("stream_duplicate_header");
            headers.set(name, value);
        }
        return { headers, start: end + 4, length: this.imageLength(headers) };
    }
    imageLength(headers) {
        const rawLength = headers.get("content-length") ?? "";
        if (!/^[1-9][0-9]{0,7}$/.test(rawLength))
            throw new Error("stream_content_length");
        const length = Number(rawLength);
        if (length > MAX_IMAGE)
            throw new Error("stream_image_limit");
        if (headers.get("content-type")?.toLowerCase() !== "image/jpeg")
            throw new Error("stream_image_type");
        return length;
    }
    readImage(start, length) {
        if (this.buffer[start + length] !== 13 || this.buffer[start + length + 1] !== 10)
            throw new Error("stream_image_length");
        const bytes = this.buffer.slice(start, start + length);
        if (bytes[0] !== 255 || bytes[1] !== 216 || bytes[bytes.length - 2] !== 255 || bytes[bytes.length - 1] !== 217)
            throw new Error("stream_jpeg");
        return bytes;
    }
    parse(parts) {
        while (!this.ended) {
            if (!this.readBoundary())
                return;
            const part = this.readHeaders();
            if (!part || this.buffer.length < part.start + part.length + 2)
                return;
            const { headers, start, length } = part;
            const bytes = this.readImage(start, length);
            parts.push({ headers, bytes, receivedAt: performance.now() });
            this.buffer = this.buffer.subarray(start + length + 2);
        }
    }
    ending(bytes) {
        for (const byte of bytes) {
            if (this.trailer >= 2 || byte !== [13, 10][this.trailer++])
                throw new Error("stream_after_end");
        }
    }
    finish() {
        if (this.trailer === 1 || this.buffer.length && !this.ended)
            throw new Error("stream_truncated");
    }
}
export async function readMjpeg(response, signal, offer) {
    if (!response.ok || !response.body)
        throw new Error("stream_unavailable");
    const parser = new MjpegParser(response.headers.get("content-type") ?? "");
    const reader = response.body.getReader();
    const cancel = () => { void reader.cancel().catch(() => undefined); };
    signal.addEventListener("abort", cancel, { once: true });
    try {
        while (!signal.aborted) {
            const { value, done } = await reader.read();
            if (done)
                break;
            for (const part of parser.feed(value)) {
                if (signal.aborted)
                    break;
                offer(part);
            }
        }
        if (!signal.aborted)
            parser.finish();
    }
    finally {
        signal.removeEventListener("abort", cancel);
        await reader.cancel().catch(() => undefined);
        reader.releaseLock();
    }
}
