import assert from "node:assert/strict";
import { test } from "node:test";

import worker from "./worker.mjs";

const SEED = new Uint8Array(32).fill(7);
const SEED_B64 = Buffer.from(SEED).toString("base64");
const ADMIN = "test-admin-token";
const CODE = "A".repeat(64);

function fakeKv() {
  const map = new Map();
  return {
    map,
    async get(key, type) {
      const value = map.get(key);
      if (value == null) return null;
      return type === "json" ? JSON.parse(value) : value;
    },
    async put(key, value) {
      map.set(key, String(value));
    },
  };
}

async function harness() {
  const env = { LICENSE_KV: fakeKv(), LICENSE_SIGNING_KEY: SEED_B64, ADMIN_TOKEN: ADMIN, LEASE_DAYS: "14" };
  const call = (path, body, headers = {}) =>
    worker.fetch(new Request("https://license.test" + path, {
      method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body || {}),
    }), env);
  return { env, call };
}

async function signingKeys() {
  const prefix = Uint8Array.from([0x30, 0x2e, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x04, 0x22, 0x04, 0x20]);
  const der = new Uint8Array(prefix.length + SEED.length);
  der.set(prefix);
  der.set(SEED, prefix.length);
  const privateKey = await crypto.subtle.importKey("pkcs8", der, { name: "Ed25519" }, true, ["sign"]);
  const jwk = await crypto.subtle.exportKey("jwk", privateKey);
  return crypto.subtle.importKey(
    "jwk", { kty: "OKP", crv: "Ed25519", x: jwk.x }, { name: "Ed25519" }, false, ["verify"],
  );
}

/** 客户端视角：对 body 原始字节验签后再解析。 */
async function open(response, publicKey) {
  const envelope = await response.json();
  const body = Buffer.from(envelope.body, "base64");
  const signature = Buffer.from(envelope.sig, "base64");
  assert.equal(await crypto.subtle.verify({ name: "Ed25519" }, publicKey, signature, body), true);
  return JSON.parse(body.toString("utf8"));
}

test("health reports the license service", async () => {
  const { call } = await harness();
  const response = await worker.fetch(new Request("https://license.test/health"), { LICENSE_KV: fakeKv() });
  assert.equal(response.status, 200);
  assert.equal((await response.json()).service, "QianniuLicense");
  assert.equal((await call("/nope", {})).status, 404);
});

test("activation signs a lease and enforces the device limit", async () => {
  const { call, env } = await harness();
  const publicKey = await signingKeys();

  const first = await call("/v1/activate", { code: CODE, device_id: "device-aaaaaaaa", machine_code: "1111-2222-3333-4444", exp: 0 });
  assert.equal(first.status, 200);
  const lease = await open(first, publicKey);
  assert.equal(lease.status, "active");
  assert.equal(lease.device_id, "device-aaaaaaaa");
  assert.ok(lease.not_after > lease.server_time + 13 * 86400);
  assert.equal(lease.lease_days, 14);

  // 同一设备重复激活不占用新名额
  assert.equal((await call("/v1/activate", { code: CODE, device_id: "device-aaaaaaaa" })).status, 200);
  // 第二台设备默认被拒绝
  const second = await call("/v1/activate", { code: CODE, device_id: "device-bbbbbbbb" });
  assert.equal(second.status, 409);
  assert.match((await second.json()).error, /设备/);

  const stored = JSON.parse(env.LICENSE_KV.map.get([...env.LICENSE_KV.map.keys()][0]));
  assert.deepEqual(stored.devices, ["device-aaaaaaaa"]);
});

test("heartbeat renews, and revoke takes effect on the next heartbeat", async () => {
  const { call } = await harness();
  const publicKey = await signingKeys();
  await call("/v1/activate", { code: CODE, device_id: "device-aaaaaaaa" });

  const before = await open(await call("/v1/heartbeat", { code: CODE, device_id: "device-aaaaaaaa", nonce: "n1" }), publicKey);
  assert.equal(before.status, "active");
  assert.equal(before.nonce, "n1");

  const headers = { Authorization: "Bearer " + ADMIN };
  assert.equal((await call("/admin/revoke", { code: CODE }, headers)).status, 200);
  const after = await open(await call("/v1/heartbeat", { code: CODE, device_id: "device-aaaaaaaa" }), publicKey);
  assert.equal(after.status, "revoked");
  assert.equal(after.not_after, 0);

  assert.equal((await call("/v1/activate", { code: CODE, device_id: "device-aaaaaaaa" })).status, 403);
});

test("admin endpoints require a token and rebind clears devices", async () => {
  const { call } = await harness();
  assert.equal((await call("/admin/lookup", { code: CODE })).status, 401);
  assert.equal((await call("/admin/lookup", { code: CODE }, { Authorization: "Bearer wrong" })).status, 401);

  const headers = { Authorization: "Bearer " + ADMIN };
  await call("/v1/activate", { code: CODE, device_id: "device-aaaaaaaa" });
  assert.equal((await call("/admin/lookup", { code: CODE }, headers)).status, 200);
  assert.equal((await call("/v1/activate", { code: CODE, device_id: "device-bbbbbbbb" })).status, 409);

  assert.equal((await call("/admin/rebind", { code: CODE }, headers)).status, 200);
  assert.equal((await call("/v1/activate", { code: CODE, device_id: "device-bbbbbbbb" })).status, 200);
});

test("registration keeps the record and expiry is reported", async () => {
  const { call } = await harness();
  const publicKey = await signingKeys();
  const headers = { Authorization: "Bearer " + ADMIN };
  const past = Math.floor(Date.now() / 1000) - 60;
  assert.equal((await call("/admin/register", { code: CODE, exp: past, memo: "客户A" }, headers)).status, 200);

  const lease = await open(await call("/v1/activate", { code: CODE, device_id: "device-aaaaaaaa" }), publicKey);
  assert.equal(lease.status, "active");
  assert.equal(lease.exp, past);

  const beat = await open(await call("/v1/heartbeat", { code: CODE, device_id: "device-aaaaaaaa" }), publicKey);
  assert.equal(beat.status, "expired");
});

test("unknown codes and foreign devices are reported, not trusted", async () => {
  const { call } = await harness();
  const publicKey = await signingKeys();
  const unknown = await open(await call("/v1/heartbeat", { code: "B".repeat(64), device_id: "device-aaaaaaaa" }), publicKey);
  assert.equal(unknown.status, "unknown");

  await call("/v1/activate", { code: CODE, device_id: "device-aaaaaaaa" });
  const mismatch = await open(await call("/v1/heartbeat", { code: CODE, device_id: "device-cccccccc" }), publicKey);
  assert.equal(mismatch.status, "device_mismatch");
});

test("malformed requests are rejected without signing", async () => {
  const { call } = await harness();
  assert.equal((await call("/v1/activate", { code: "short", device_id: "device-aaaaaaaa" })).status, 400);
  assert.equal((await call("/v1/activate", { code: CODE, device_id: "../" })).status, 400);
  assert.equal((await call("/v1/heartbeat", { code: CODE, device_id: "device-aaaaaaaa", nonce: "bad nonce!" })).status, 200);
});
