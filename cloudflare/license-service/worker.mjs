// 授权服务：激活登记、心跳（服务端签名响应）、吊销与设备数限制。
// 数据存 KV；响应体用 Ed25519 私钥签名，客户端只认签名，防止伪造“已授权”。
const SCHEMA = 1;
const MAX_DEVICES_LIMIT = 8;
const LEASE_MAX_DAYS = 60;
const encoder = new TextEncoder();

function json(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function b64ToBytes(value) {
  const text = String(value || "");
  if (!text) return new Uint8Array(0);
  const raw = atob(text);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

function bytesToB64(bytes) {
  let text = "";
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text);
}

function hex(bytes) {
  return [...bytes].map(b => b.toString(16).padStart(2, "0")).join("");
}

async function digest(value) {
  return hex(new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(value))));
}

// 与客户端 desktop/license.py 的 normalize_code 保持一致。
function normalizeCode(code) {
  return String(code || "").toUpperCase().replace(/[^A-Z2-7]/g, "");
}

function cleanId(value, max = 64) {
  const text = String(value || "").trim();
  return /^[A-Za-z0-9_-]{8,64}$/.test(text) && text.length <= max ? text : "";
}

function nonce(value) {
  const text = String(value || "");
  return /^[A-Za-z0-9_-]{1,64}$/.test(text) ? text : "";
}

function leaseDays(env) {
  const value = Number.parseInt(String(env.LEASE_DAYS || "14"), 10);
  return Number.isFinite(value) ? Math.min(LEASE_MAX_DAYS, Math.max(1, value)) : 14;
}

// Ed25519 私钥的 DER 包装：PKCS#8 里嵌入 32 字节种子，兼容 Workers 与 Node 运行时。
const PKCS8_PREFIX = Uint8Array.from([
  0x30, 0x2e, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x04, 0x22, 0x04, 0x20,
]);

function pkcs8(seed) {
  const der = new Uint8Array(PKCS8_PREFIX.length + seed.length);
  der.set(PKCS8_PREFIX);
  der.set(seed, PKCS8_PREFIX.length);
  return der;
}

let signingCache = null;

async function signingKey(env) {
  const secret = String(env.LICENSE_SIGNING_KEY || "");
  if (!secret) throw new Error("LICENSE_SIGNING_KEY 未配置");
  if (signingCache && signingCache.secret === secret) return signingCache.value;
  const raw = b64ToBytes(secret);
  if (raw.length !== 32) throw new Error("LICENSE_SIGNING_KEY 长度必须为 32 字节");
  let value;
  try {
    const algorithm = { name: "Ed25519" };
    const key = await crypto.subtle.importKey("pkcs8", pkcs8(raw), algorithm, false, ["sign"]);
    value = { key, algorithm };
  } catch {
    try {
      const algorithm = { name: "Ed25519" };
      const key = await crypto.subtle.importKey("raw", raw, algorithm, false, ["sign"]);
      value = { key, algorithm };
    } catch {
      // 旧版 Workers 运行时只提供 NODE-ED25519 别名。
      const algorithm = { name: "NODE-ED25519", namedCurve: "NODE-ED25519" };
      const key = await crypto.subtle.importKey("raw", raw, algorithm, false, ["sign"]);
      value = { key, algorithm };
    }
  }
  signingCache = { secret, value };
  return value;
}

/** 统一签名响应：客户端对 body 的原始字节验签后再解析 JSON。 */
async function signed(env, payload) {
  const body = JSON.stringify(payload);
  const bytes = encoder.encode(body);
  const { key, algorithm } = await signingKey(env);
  const signature = new Uint8Array(await crypto.subtle.sign(algorithm, key, bytes));
  return json({ body: bytesToB64(bytes), sig: bytesToB64(signature) });
}

function timingSafeEqual(left, right) {
  const a = encoder.encode(String(left));
  const b = encoder.encode(String(right));
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a[i] ^ b[i];
  return diff === 0;
}

function authorized(request, env) {
  const expected = String(env.ADMIN_TOKEN || "");
  if (!expected) return false;
  const header = request.headers.get("Authorization") || "";
  if (!header.startsWith("Bearer ")) return false;
  return timingSafeEqual(header.slice(7), expected);
}

async function codeKey(code) {
  return "code:" + (await digest(normalizeCode(code)));
}

async function readRecord(env, key) {
  if (!env.LICENSE_KV) throw new Error("LICENSE_KV 未绑定");
  const value = await env.LICENSE_KV.get(key, "json");
  return value && typeof value === "object" ? value : null;
}

async function writeRecord(env, key, record) {
  await env.LICENSE_KV.put(key, JSON.stringify(record));
}

function deviceList(record) {
  return Array.isArray(record?.devices) ? record.devices.filter(item => typeof item === "string" && item) : [];
}

function maxDevices(record, env) {
  const recordValue = Number(record?.max_devices);
  if (Number.isSafeInteger(recordValue) && recordValue > 0) return Math.min(MAX_DEVICES_LIMIT, recordValue);
  const envValue = Number.parseInt(String(env.MAX_DEVICES || "1"), 10);
  return Number.isSafeInteger(envValue) && envValue > 0 ? Math.min(MAX_DEVICES_LIMIT, envValue) : 1;
}

/** 激活：登记设备（受设备数限制）并下发带签名的租约。 */
async function activate(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "请求格式不正确" }, 400);
  }
  const code = normalizeCode(body.code);
  const device = cleanId(body.device_id);
  if (code.length < 40) return json({ error: "激活码格式不正确" }, 400);
  if (!device) return json({ error: "设备标识无效，请重启软件后重试" }, 400);

  const now = Math.floor(Date.now() / 1000);
  const key = await codeKey(code);
  let record = await readRecord(env, key);
  if (record?.revoked) return json({ error: "该激活码已被停用，请联系卖家。" }, 403);

  const devices = deviceList(record);
  if (!devices.includes(device)) {
    if (devices.length >= maxDevices(record, env)) {
      return json({ error: `该激活码已在 ${devices.length} 台设备上使用，请让卖家换绑后再激活。` }, 409);
    }
    devices.push(device);
  }

  const exp = Number.isSafeInteger(record?.exp) ? record.exp : Number(body.exp) || 0;
  const machine = String(body.machine_code || "").slice(0, 32);
  record = {
    ...(record || {}),
    code_hash: key.slice(5),
    machine_code: record?.machine_code || machine,
    exp,
    memo: String(record?.memo ?? body.memo ?? "").slice(0, 40),
    max_devices: maxDevices(record, env),
    revoked: Boolean(record?.revoked),
    devices,
    created_at: record?.created_at || now,
    updated_at: now,
    last_seen: now,
  };
  await writeRecord(env, key, record);

  const days = leaseDays(env);
  return signed(env, {
    v: SCHEMA,
    status: "active",
    code_hash: record.code_hash,
    device_id: device,
    machine_code: record.machine_code,
    exp,
    not_after: now + days * 86400,
    lease_days: days,
    server_time: now,
    nonce: nonce(body.nonce),
  });
}

/** 心跳：返回吊销/过期/换机状态并续租；不存在的码返回 unknown。 */
async function heartbeat(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "请求格式不正确" }, 400);
  }
  const code = normalizeCode(body.code);
  const device = cleanId(body.device_id);
  if (code.length < 40) return json({ error: "激活码格式不正确" }, 400);
  if (!device) return json({ error: "设备标识无效" }, 400);

  const now = Math.floor(Date.now() / 1000);
  const key = await codeKey(code);
  const record = await readRecord(env, key);
  const days = leaseDays(env);
  let status = "unknown";
  if (record) {
    if (!deviceList(record).includes(device)) status = "device_mismatch";
    else if (record.revoked) status = "revoked";
    else if (Number(record.exp) > 0 && now > Number(record.exp)) status = "expired";
    else status = "active";
  }
  if (status === "active" && now - Number(record.last_seen || 0) > 3600) {
    await writeRecord(env, key, { ...record, last_seen: now, updated_at: now });
  }
  return signed(env, {
    v: SCHEMA,
    status,
    code_hash: key.slice(5),
    device_id: device,
    machine_code: String(record?.machine_code || ""),
    exp: Number(record?.exp) || 0,
    not_after: status === "active" ? now + days * 86400 : 0,
    lease_days: days,
    server_time: now,
    nonce: nonce(body.nonce),
  });
}

async function admin(request, env, action) {
  if (!authorized(request, env)) return json({ error: "管理令牌无效" }, 401);
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "请求格式不正确" }, 400);
  }
  const code = normalizeCode(body.code);
  if (code.length < 40) return json({ error: "激活码格式不正确" }, 400);
  const now = Math.floor(Date.now() / 1000);
  const key = await codeKey(code);
  const record = await readRecord(env, key);

  if (action === "lookup") {
    if (!record) return json({ error: "该激活码未在服务端登记" }, 404);
    return json({ ok: true, record });
  }
  if (action === "register") {
    const exp = Number.isSafeInteger(body.exp) ? body.exp : 0;
    const limit = Math.min(MAX_DEVICES_LIMIT, Math.max(1, Number(body.max_devices) || 1));
    const next = {
      ...(record || {}),
      code_hash: key.slice(5),
      machine_code: String(body.machine_code || record?.machine_code || "").slice(0, 32),
      exp,
      memo: String(body.memo ?? record?.memo ?? "").slice(0, 40),
      max_devices: limit,
      revoked: Boolean(record?.revoked),
      devices: deviceList(record),
      created_at: record?.created_at || now,
      updated_at: now,
      last_seen: Number(record?.last_seen || 0),
    };
    await writeRecord(env, key, next);
    return json({ ok: true, record: next });
  }
  if (!record) return json({ error: "该激活码未在服务端登记" }, 404);
  if (action === "revoke") {
    await writeRecord(env, key, { ...record, revoked: true, updated_at: now });
    return json({ ok: true, revoked: true });
  }
  if (action === "unrevoke") {
    await writeRecord(env, key, { ...record, revoked: false, updated_at: now });
    return json({ ok: true, revoked: false });
  }
  if (action === "rebind") {
    await writeRecord(env, key, { ...record, devices: [], updated_at: now });
    return json({ ok: true, devices: [] });
  }
  return json({ error: "未知管理操作" }, 404);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { status: 204 });
    if (url.pathname === "/health") {
      return json({ ok: true, service: "QianniuLicense", schema: SCHEMA });
    }
    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405, headers: { Allow: "POST" } });
    }
    try {
      if (url.pathname === "/v1/activate") return await activate(request, env);
      if (url.pathname === "/v1/heartbeat") return await heartbeat(request, env);
      const match = /^\/admin\/(register|revoke|unrevoke|rebind|lookup)$/.exec(url.pathname);
      if (match) return await admin(request, env, match[1]);
      return json({ error: "Not found" }, 404);
    } catch (error) {
      console.error("license service error:", error);
      return json({ error: "授权服务暂时不可用" }, 503);
    }
  },
};
