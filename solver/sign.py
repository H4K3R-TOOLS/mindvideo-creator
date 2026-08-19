# Python 3.11 | solver/sign.py
# Purpose: Generate i-sign header by running WASM via Node.js subprocess
# WASM: sign_wasm_bg.1b347e57.wasm (fetched from mindvideo CDN)
# Algorithm (reverse engineered from 64576-53a187b734a4ca24.js):
#   nonce      = random 16-char alphanumeric
#   timestamp  = Date.now() (ms)
#   params     = {body_params..., url_params..., timestamp, nonce}
#   sorted_qs  = qs.stringify(params, {sort: alphabetical, arrayFormat:'indices'})
#   sign       = WASM.get_sign(true, f"{origin}{path}?{sorted_qs}")
#   i-sign     = btoa(JSON.stringify({nonce, timestamp, sign}))
#
# Node.js subprocess handles WASM execution — avoids Python WASM runtime complexity.

import asyncio
import json
import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)

_NODE_SCRIPT = r"""
const fs = require('fs');
const path = require('path');

async function main() {
  const input = JSON.parse(process.argv[2]);
  const { wasmPath, url, params } = input;

  // Load WASM module (same bindgen wrappers as browser)
  const wasmBytes = fs.readFileSync(wasmPath);

  // Replicate wasm-bindgen memory helpers
  const heap = new Array(128).fill(undefined);
  heap.push(undefined, null, true, false);
  let heap_next = heap.length;

  function addHeapObject(obj) {
    if (heap_next === heap.length) heap.push(heap.length + 1);
    const idx = heap_next;
    heap_next = heap[idx];
    heap[idx] = obj;
    return idx;
  }

  function getObject(idx) { return heap[idx]; }

  function dropObject(idx) {
    if (idx < 132) return;
    heap[idx] = heap_next;
    heap_next = idx;
  }

  function takeObject(idx) {
    const ret = getObject(idx);
    dropObject(idx);
    return ret;
  }

  let cachedUint8Memory = null;
  let cachedDataView = null;
  let wasm;

  function getUint8Memory() {
    if (!cachedUint8Memory || cachedUint8Memory.byteLength === 0) {
      cachedUint8Memory = new Uint8Array(wasm.memory.buffer);
    }
    return cachedUint8Memory;
  }

  function getDataView() {
    if (!cachedDataView || cachedDataView.buffer !== wasm.memory.buffer) {
      cachedDataView = new DataView(wasm.memory.buffer);
    }
    return cachedDataView;
  }

  const enc = new TextEncoder();
  const dec = new TextDecoder('utf-8', { ignoreBOM: true, fatal: true });
  let WASM_STR_LEN = 0;

  function passStringToWasm(arg, malloc, realloc) {
    const encoded = enc.encode(arg);
    const ptr = malloc(encoded.length, 1) >>> 0;
    getUint8Memory().subarray(ptr, ptr + encoded.length).set(encoded);
    WASM_STR_LEN = encoded.length;
    return ptr;
  }

  function getStringFromWasm(ptr, len) {
    return dec.decode(getUint8Memory().subarray(ptr, ptr + len));
  }

  function handleError(f, args) {
    try { return f.apply(this, args); }
    catch (e) { wasm.__wbindgen_export_0(addHeapObject(e)); }
  }

  const imports = {
    wbg: {
      __wbg_call_672a4d21634d4a24: (a, b) => handleError(() => addHeapObject(getObject(a).call(getObject(b))), []),
      __wbg_call_7cccdd69e0791ae2: (a, b, c) => handleError(() => addHeapObject(getObject(a).call(getObject(b), getObject(c))), []),
      __wbg_getTime_46267b1c24877e30: (a) => getObject(a).getTime(),
      __wbg_get_67b2ba62fc30de12: (a, b) => handleError(() => addHeapObject(Reflect.get(getObject(a), getObject(b))), []),
      __wbg_has_a5ea9117f258a0ec: (a, b) => handleError(() => Reflect.has(getObject(a), getObject(b)), []),
      __wbg_new0_f788a2397c7ca929: () => addHeapObject(new Date()),
      __wbg_newnoargs_105ed471475aaf50: (a, b) => addHeapObject(new Function(getStringFromWasm(a, b))),
      __wbg_static_accessor_GLOBAL_88a902d13a557d07: () => { try { return addHeapObject(globalThis); } catch { return 0; } },
      __wbg_static_accessor_GLOBAL_THIS_56578be7e9f832b0: () => { try { return addHeapObject(globalThis); } catch { return 0; } },
      __wbg_static_accessor_SELF_37c5d418e4bf5819: () => { try { return addHeapObject(globalThis); } catch { return 0; } },
      __wbg_static_accessor_WINDOW_5de37043a91a9c40: () => { try { return addHeapObject(globalThis); } catch { return 0; } },
      __wbindgen_is_function: (a) => typeof getObject(a) === 'function',
      __wbindgen_is_null: (a) => getObject(a) === null,
      __wbindgen_is_object: (a) => { const v = getObject(a); return typeof v === 'object' && v !== null; },
      __wbindgen_is_undefined: (a) => getObject(a) === undefined,
      __wbindgen_object_clone_ref: (a) => addHeapObject(getObject(a)),
      __wbindgen_object_drop_ref: (a) => takeObject(a),
      __wbindgen_string_new: (a, b) => addHeapObject(getStringFromWasm(a, b)),
      __wbindgen_throw: (a, b) => { throw new Error(getStringFromWasm(a, b)); },
    }
  };

  const { instance } = await WebAssembly.instantiate(wasmBytes, imports);
  wasm = instance.exports;

  // get_sign(key: bool, query_string: &str) -> String
  function get_sign(key, query_string) {
    const retptr = wasm.__wbindgen_add_to_stack_pointer(-16);
    const ptr = passStringToWasm(query_string, wasm.__wbindgen_export_1, wasm.__wbindgen_export_2);
    const len = WASM_STR_LEN;
    try {
      wasm.get_sign(retptr, key, ptr, len);
      const r0 = getDataView().getInt32(retptr + 0, true);
      const r1 = getDataView().getInt32(retptr + 4, true);
      return getStringFromWasm(r0, r1);
    } finally {
      wasm.__wbindgen_add_to_stack_pointer(16);
      wasm.__wbindgen_export_3(r0, r1, 1);
    }
  }

  // Replicate qs.stringify with {arrayFormat:'indices', sort: alphabetical}
  function qsStringify(obj) {
    const flat = [];
    function recurse(val, prefix) {
      if (val === null || val === undefined) return;
      if (Array.isArray(val)) {
        val.forEach((v, i) => recurse(v, `${prefix}[${i}]`));
      } else if (typeof val === 'object') {
        Object.keys(val).sort().forEach(k => recurse(val[k], prefix ? `${prefix}[${k}]` : k));
      } else {
        flat.push([prefix, String(val)]);
      }
    }
    Object.keys(obj).sort().forEach(k => recurse(obj[k], k));
    flat.sort((a, b) => a[0] > b[0] ? 1 : -1);
    return flat.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&');
  }

  // Build sign
  const parsedUrl = new URL(url);
  const urlParams = Object.fromEntries(parsedUrl.searchParams.entries());
  const nonce = Array.from({length: 16}, () => 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'[Math.floor(Math.random() * 62)]).join('');
  const timestamp = Date.now();

  const merged = { ...urlParams, ...params, timestamp: String(timestamp), nonce };
  // Remove undefined
  Object.keys(merged).forEach(k => merged[k] === undefined && delete merged[k]);

  const qs = qsStringify(merged);
  const signInput = `${parsedUrl.origin}${parsedUrl.pathname}?${qs}`;
  const sign = get_sign(true, signInput);

  const result = Buffer.from(JSON.stringify({ nonce, timestamp, sign })).toString('base64');
  process.stdout.write(JSON.stringify({ isign: result, nonce, timestamp, sign }));
}

main().catch(e => { process.stderr.write(String(e)); process.exit(1); });
"""

_WASM_URL   = "https://www.mindvideo.ai/_next/static/media/sign_wasm_bg.1b347e57.wasm"
_WASM_CACHE = os.path.join(os.path.dirname(__file__), "_sign_wasm_bg.wasm")
_NODE_CACHE = os.path.join(os.path.dirname(__file__), "_sign_worker.js")

_wasm_ready = False


def _ensure_files() -> None:
    global _wasm_ready
    if _wasm_ready:
        return
    # Write Node.js script
    with open(_NODE_CACHE, "w", encoding="utf-8") as f:
        f.write(_NODE_SCRIPT)
    # Download WASM with browser headers (CF CDN blocks plain urllib — 403)
    if not os.path.exists(_WASM_CACHE):
        import httpx
        logger.info("Downloading sign_wasm_bg.wasm...")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Referer":        "https://www.mindvideo.ai/auth/signup/",
            "Accept":         "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = httpx.get(_WASM_URL, headers=headers, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        with open(_WASM_CACHE, "wb") as f:
            f.write(resp.content)
        logger.info(f"WASM saved: {_WASM_CACHE} ({len(resp.content)} bytes)")
    _wasm_ready = True


async def generate(url: str, body_params: dict) -> str:
    """
    Generate i-sign header value for the given API URL and request body.
    Spawns Node.js subprocess — requires node >=18 in PATH.
    Returns base64 i-sign string.
    """
    _ensure_files()
    payload = json.dumps({"wasmPath": _WASM_CACHE, "url": url, "params": body_params})
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            ["node", _NODE_CACHE, payload],
            capture_output=True,
            text=True,
            timeout=10,
        ),
    )
    if result.returncode != 0:
        raise RuntimeError(f"sign worker failed: {result.stderr}")
    data = json.loads(result.stdout)
    logger.debug(f"i-sign generated: nonce={data['nonce']} ts={data['timestamp']}")
    return data["isign"]
