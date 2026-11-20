/* A read-only reader for the `.kpack` files the desktop app installs.
 *
 * A `.kpack` is a SQLite database. The extension cannot run SQLite, and the
 * offline path must not guess at a binary format: this reader walks the
 * database the way SQLite's own file format describes it - the header, the
 * `sqlite_master` table, each table's B-tree, and overflow pages for a long
 * payload - and returns whole rows for the few tables the lookup needs.
 *
 * It never writes, never follows a pointer outside the file, and refuses a
 * file that does not start with SQLite's own header. A malformed pack is an
 * error with a sentence, not a silent empty catalog.
 *
 * Loaded as a classic script before `background.js` (Firefox lists both in
 * `background.scripts`; Chromium's service worker imports this file), and
 * tested in Node directly.
 */
(function (root) {
  "use strict";

  const HEADER = "SQLite format 3\u0000";

  function read(bytes, tableNames) {
    const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    if (data.length < 512) throw new Error("not a SQLite file: too short");
    for (let i = 0; i < HEADER.length; i += 1) {
      if (data[i] !== HEADER.charCodeAt(i)) throw new Error("not a SQLite file: bad header");
    }
    const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
    const pageSize = view.getUint16(16) === 1 ? 65536 : view.getUint16(16);
    if (pageSize < 512 || (pageSize & (pageSize - 1)) !== 0) {
      throw new Error(`not a SQLite file: page size ${pageSize}`);
    }
    const reserved = data[20] || 0;
    const usable = pageSize - reserved;
    if (usable < 480) throw new Error("not a SQLite file: unusable page size");

    const pageAt = (number) => {
      const start = (number - 1) * pageSize;
      if (number < 1 || start + pageSize > data.length) throw new Error("truncated pack");
      return data.subarray(start, start + pageSize);
    };

    const roots = new Map();
    walk(pageAt(1), 100, (row) => {
      if (row[0] === "table" && typeof row[1] === "string") roots.set(row[1], Number(row[3]));
    });

    const out = {};
    for (const name of tableNames) {
      const rootPage = roots.get(name);
      if (!rootPage) continue;
      const rows = [];
      walk(pageAt(rootPage), 0, (row) => rows.push(row));
      out[name] = rows;
    }
    return out;

    /* Walk one table B-tree. `header` is 100 on page 1 and 0 elsewhere. */
    function walk(page, header, onRow) {
      const type = page[header];
      if (type !== 0x0d && type !== 0x05) throw new Error(`not a table page: ${type}`);
      const count = view.getUint16((page.byteOffset - data.byteOffset) + header + 3, false);
      const pointersAt = header + (type === 0x05 ? 12 : 8);
      const base = page.byteOffset - data.byteOffset;
      for (let i = 0; i < count; i += 1) {
        const at = pointersAt + i * 2;
        const cell = view.getUint16(base + at, false);
        if (type === 0x0d) onRow(tableCell(page, cell));
        else {
          const child = view.getUint32(base + cell, false);
          walk(pageAt(child), 0, onRow);
        }
      }
      if (type === 0x05) walk(pageAt(view.getUint32(base + header + 8, false)), 0, onRow);
    }

    /* A table leaf cell: payload length, rowid, payload (local + overflow). */
    function tableCell(page, offset) {
      const base = page.byteOffset - data.byteOffset;
      const [length, afterLength] = varint(page, offset);
      const [, afterRowid] = varint(page, afterLength);
      const payload = payloadOf(page, afterRowid, length);
      return record(payload);
    }

    function payloadOf(page, offset, length) {
      const base = page.byteOffset - data.byteOffset;
      const maxLocal = usable - 35;
      const minLocal = Math.floor(((usable - 12) * 32) / 255) - 23;
      let local = length;
      if (length > maxLocal) {
        const k = minLocal + ((length - minLocal) % (usable - 4));
        local = k <= maxLocal ? k : minLocal;
      }
      const start = base + offset;
      if (offset + local > page.length) throw new Error("cell runs past its page");
      const parts = [page.subarray(offset, offset + local)];
      if (local < length) {
        let next = view.getUint32(base + offset + local, false);
        let remaining = length - local;
        let guard = 0;
        while (next && remaining > 0) {
          if (guard++ > 100000) throw new Error("overflow chain did not end");
          const overflow = pageAt(next);
          const obase = overflow.byteOffset - data.byteOffset;
          next = view.getUint32(obase, false);
          const take = Math.min(usable - 4, remaining);
          parts.push(overflow.subarray(4, 4 + take));
          remaining -= take;
        }
        if (remaining !== 0) throw new Error("overflow chain ended early");
      }
      return concat(parts);
    }

    /* A record: header length, serial types, then values. */
    function record(payload) {
      const [headerLength, afterHeader] = varint(payload, 0);
      const types = [];
      let at = afterHeader;
      while (at < headerLength) {
        const [type, next] = varint(payload, at);
        types.push(type);
        at = next;
      }
      const values = [];
      let body = headerLength;
      for (const type of types) {
        const [value, next] = valueOf(payload, body, type);
        values.push(value);
        body = next;
      }
      return values;
    }

    function valueOf(payload, offset, type) {
      const view = new DataView(payload.buffer, payload.byteOffset, payload.byteLength);
      const size = [0, 1, 2, 3, 4, 6, 8, 8, 0, 0, 0, 0][type];
      if (type === 0) return [null, offset];
      if (type >= 12) {
        const length = type % 2 === 0 ? (type - 12) / 2 : (type - 13) / 2;
        const bytes = payload.subarray(offset, offset + length);
        const text = type % 2 === 0 ? bytes : decode(bytes);
        return [text, offset + length];
      }
      if (size === undefined) throw new Error(`unsupported serial type ${type}`);
      if (type === 7) return [view.getFloat64(offset, false), offset + 8];
      if (type === 8) return [0, offset];
      if (type === 9) return [1, offset];
      let value = 0;
      for (let i = 0; i < size; i += 1) value = value * 256 + payload[offset + i];
      const limit = Math.pow(2, size * 8 - 1);
      if (value >= limit) value -= limit * 2;
      return [value, offset + size];
    }
  }

  function varint(bytes, offset) {
    let value = 0;
    for (let i = 0; i < 9; i += 1) {
      const byte = bytes[offset + i];
      if (byte === undefined) throw new Error("varint runs past its cell");
      if (i === 8) return [value * 256 + byte, offset + 9];
      value = value * 128 + (byte & 0x7f);
      if ((byte & 0x80) === 0) return [value, offset + i + 1];
    }
    throw new Error("varint too long");
  }

  function concat(parts) {
    if (parts.length === 1) return parts[0];
    const length = parts.reduce((sum, part) => sum + part.length, 0);
    const out = new Uint8Array(length);
    let at = 0;
    for (const part of parts) {
      out.set(part, at);
      at += part.length;
    }
    return out;
  }

  function decode(bytes) {
    if (typeof TextDecoder !== "undefined") return new TextDecoder("utf-8").decode(bytes);
    let out = "";
    for (const byte of bytes) out += String.fromCharCode(byte);
    return out;
  }

  root.KrikoSqlite = { read };
})(typeof globalThis !== "undefined" ? globalThis : this);
