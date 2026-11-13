import assert from "node:assert/strict";
import { test } from "node:test";
import worker from "./worker.mjs";

const sha = "a".repeat(64);
const url = `/releases/${sha}/QianniuApp-1.3.0.2.zip`;
const chunks = [`/__updates/chunks/${sha}/0000.bin`, `/__updates/chunks/${sha}/0001.bin`];
const feed = { schema: 1, version: "1.3.0.2", url, size: 6, sha256: sha, notes: "更新" };
function fixture({ empty = false, missing = false, probe = false } = {}) {
  const manifest = { schema: 1, application: "QianniuUpdater", feed: empty ? { schema: 1, version: "0.0.0", sha256: "", size: 0 } : feed, releases: { [sha]: { ...feed, chunks } } };
  const calls = [], tasks = [];
  if (probe) manifest.download_probe = { ...feed, url: "/download-check.bin", chunks };
  const env = { ASSETS: { async fetch(input) {
    const path = new URL(typeof input === "string" ? input : input.url).pathname;
    calls.push(path);
    if (path === "/__updates/index.json") return Response.json(manifest);
    if (path === chunks[0]) return new Response(new Uint8Array([1, 2, 3]));
    if (path === chunks[1] && !missing) return new Response(new Uint8Array([4, 5, 6]));
    return new Response("Not found", { status: 404 });
  } } };
  const get = (path, init = {}) => worker.fetch(new Request("https://download.test" + path, init), env, { waitUntil: p => tasks.push(p) });
  return { get, calls, tasks, manifest };
}

test("latest.json returns a relative immutable ZIP URL without caching", async () => {
  const { get } = fixture();
  const response = await get("/latest.json");
  assert.deepEqual(await response.json(), feed);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
});

test("initial service advertises no update", async () => {
  const { get } = fixture({ empty: true });
  assert.equal((await (await get("/latest.json")).json()).version, "0.0.0");
  assert.equal((await (await get("/health")).json()).published, false);
});

test("binary probe validates the same chunk stream without publishing an update", async () => {
  const { get, tasks } = fixture({ empty: true, probe: true });
  const response = await get("/download-check.bin");
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Content-Type"), "application/octet-stream");
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual([...new Uint8Array(await response.arrayBuffer())], [1, 2, 3, 4, 5, 6]);
  await Promise.all(tasks);
  assert.equal((await (await get("/health")).json()).published, false);
});

test("download concatenates exact binary bytes and supplies the full length", async () => {
  const { get, tasks, calls } = fixture();
  const response = await get(url);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Content-Length"), "6");
  assert.equal(response.headers.get("ETag"), `"${sha}"`);
  assert.deepEqual([...new Uint8Array(await response.arrayBuffer())], [1, 2, 3, 4, 5, 6]);
  await Promise.all(tasks);
  assert.deepEqual(calls, ["/__updates/index.json", ...chunks]);
});

test("delta ZIPs stream through declared immutable release URLs", async () => {
  const { get, tasks, manifest } = fixture();
  const deltaUrl = url.replace(".zip", "-from-1.3.0.1.delta.zip");
  manifest.releases[sha].url = deltaUrl;
  manifest.feed = { ...feed, deltas: [{ base_version: "1.3.0.1", url: deltaUrl, size: 6, sha256: sha }] };
  const response = await get(deltaUrl);
  assert.equal(response.status, 200);
  assert.deepEqual([...new Uint8Array(await response.arrayBuffer())], [1, 2, 3, 4, 5, 6]);
  await Promise.all(tasks);
  assert.equal((await (await get("/latest.json")).json()).deltas[0].url, deltaUrl);
  assert.equal((await get(deltaUrl.replace("1.3.0.1", "1.3.0.0"))).status, 404);
});

test("HEAD never opens chunk bodies and ETag supports revalidation", async () => {
  const { get, calls } = fixture();
  const response = await get(url, { method: "HEAD" });
  assert.equal(await response.text(), "");
  assert.equal(response.headers.get("Content-Length"), "6");
  assert.deepEqual(calls, ["/__updates/index.json"]);
  assert.equal((await get(url, { headers: { "If-None-Match": `"${sha}"` } })).status, 304);
});

test("only read endpoints and declared release paths are public", async () => {
  const { get } = fixture();
  assert.equal((await get("/latest.json", { method: "PUT", body: "overwrite" })).status, 405);
  assert.equal((await get("/__updates/index.json")).status, 404);
  assert.equal((await get(chunks[0])).status, 404);
  assert.equal((await get(url.replace("1.3.0.2", "9.9.9"))).status, 404);
  assert.equal((await get(url, { headers: { Range: "bytes=0-1" } })).status, 416);
});

test("missing chunk aborts transfer so the client cannot accept truncated ZIPs", async () => {
  const { get, tasks } = fixture({ missing: true });
  const response = await get(url);
  await assert.rejects(response.arrayBuffer());
  await Promise.all(tasks);
});
