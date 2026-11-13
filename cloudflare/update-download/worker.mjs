// 下载端只提供读取。更新 ZIP 的分块由部署脚本生成，客户端仍下载完整 ZIP。
const EMPTY_FEED = { schema: 1, version: "0.0.0", url: "", sha256: "", size: 0, notes: "尚未发布更新" };

function json(value, status = 200, head = false) {
  return new Response(head ? null : JSON.stringify(value), {
    status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" },
  });
}

async function index(env) {
  const response = await env.ASSETS.fetch("https://assets.invalid/__updates/index.json");
  if (!response.ok) throw new Error("Download manifest unavailable");
  const value = await response.json();
  if (value.schema !== 1 || value.application !== "QianniuUpdater") throw new Error("Invalid download manifest");
  return value;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const head = request.method === "HEAD";
    if (request.method !== "GET" && !head) return new Response("Method not allowed", { status: 405, headers: { Allow: "GET, HEAD" } });
    try {
      const manifest = await index(env);
      const feed = manifest.feed || EMPTY_FEED;
      if (url.pathname === "/health") return json({ ok: true, application: "QianniuUpdater", published: feed.version !== "0.0.0", version: feed.version }, 200, head);
      if (url.pathname === "/latest.json") return json(feed, 200, head);
      if (url.pathname === "/") return new Response(head ? null : "千牛自动上架更新下载服务\n更新地址：" + url.origin + "/latest.json\n" + (feed.version === "0.0.0" ? "尚未发布更新" : "最新版本：" + feed.version), {
        headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
      });
      const match = /^\/releases\/([a-f0-9]{64})\/QianniuApp-[\d.]+(?:-from-[\d.]+\.delta)?\.zip$/.exec(url.pathname);
      const probe = url.pathname === "/download-check.bin";
      const release = probe ? manifest.download_probe : match && manifest.releases?.[match[1]];
      if (!release || release.url !== url.pathname) return new Response("Not found", { status: 404 });
      const sha = probe ? release.sha256 : match[1];
      if (!/^[a-f0-9]{64}$/.test(sha)) throw new Error("Invalid release checksum");
      if (!Number.isSafeInteger(release.size) || release.size <= 0 || !Array.isArray(release.chunks) || release.chunks.length > 40) throw new Error("Invalid release");
      const headers = new Headers({ "Content-Type": probe ? "application/octet-stream" : "application/zip", "Content-Length": String(release.size),
        "Content-Disposition": `attachment; filename="${url.pathname.split("/").pop()}"`,
        "ETag": `"${sha}"`, "Cache-Control": probe ? "no-store" : "public, max-age=31536000, immutable", "Accept-Ranges": "none", "X-Content-Type-Options": "nosniff" });
      if (request.headers.get("If-None-Match") === headers.get("ETag")) return new Response(null, { status: 304, headers });
      if (request.headers.has("Range")) return new Response(null, { status: 416, headers: { "Content-Range": `bytes */${release.size}` } });
      if (head) return new Response(null, { headers });

      // FixedLengthStream 让 Workers 按准确大小输出，同时检测传输截断。
      const stream = typeof FixedLengthStream === "function" ? new FixedLengthStream(release.size) : new TransformStream();
      const transfer = (async () => {
        for (const chunk of release.chunks) {
          if (!/^\/__updates\/chunks\/[a-f0-9]{64}\/\d{4}\.bin$/.test(chunk)) throw new Error("Invalid chunk path");
          const response = await env.ASSETS.fetch(new Request("https://assets.invalid" + chunk, { headers: { "Accept-Encoding": "identity" } }));
          if (!response.ok || !response.body) throw new Error("Download chunk unavailable");
          // 原生流转发，无须把整个 ZIP 放进 Worker 内存。
          await response.body.pipeTo(stream.writable, { preventClose: true });
        }
        await stream.writable.close();
      })().catch(async error => {
        try { await stream.writable.abort(error); } catch { /* 客户端断开连接 */ }
      });
      ctx.waitUntil(transfer);
      return new Response(stream.readable, { headers });
    } catch {
      return json({ error: "更新下载服务暂时不可用" }, 503, head);
    }
  },
};
