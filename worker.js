// DUCKTAPE Industrial — Cloudflare Worker Edge Relay
// Zero-cloud / Zero-log ultra-fast streaming edge relay created for Aman Srivastava's DUCKTAPE

const manifests = new Map();
const sseControllers = new Map();

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "*",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    const path = url.pathname;

    // Health check
    if (path === "/" || path === "/health") {
      return new Response("DUCKTAPE Cloudflare Edge Relay is Online and Active", {
        headers: { ...corsHeaders, "Content-Type": "text/plain" }
      });
    }

    // Manifest Publish / Poll: /api/manifest/:sid
    if (path.startsWith("/api/manifest/")) {
      const sid = path.split("/")[3];
      if (request.method === "POST") {
        const body = await request.text();
        manifests.set(sid, { body, time: Date.now() });
        return new Response(JSON.stringify({ status: "published" }), {
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      } else {
        const data = manifests.get(sid);
        if (!data) {
          return new Response(JSON.stringify({ error: "manifest_not_found" }), {
            status: 404,
            headers: { ...corsHeaders, "Content-Type": "application/json" }
          });
        }
        return new Response(data.body, {
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      }
    }

    // Signal & File Chunk Relay: /api/signal/:topic
    if (path.startsWith("/api/signal/")) {
      const topic = path.split("/")[3];
      if (request.method === "POST") {
        const body = await request.text();
        const targets = sseControllers.get(topic) || [];
        for (const controller of targets) {
          try {
            controller.enqueue(new TextEncoder().encode(`data: ${body}\n\n`));
          } catch(e) {}
        }
        return new Response(JSON.stringify({ delivered: targets.length }), {
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      } else {
        // SSE Stream Endpoint
        const stream = new ReadableStream({
          start(controller) {
            if (!sseControllers.has(topic)) sseControllers.set(topic, []);
            sseControllers.get(topic).push(controller);
          },
          cancel() {
            if (sseControllers.has(topic)) {
              const list = sseControllers.get(topic).filter(c => c !== controller);
              if (list.length) sseControllers.set(topic, list);
              else sseControllers.delete(topic);
            }
          }
        });

        return new Response(stream, {
          headers: {
            ...corsHeaders,
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
          }
        });
      }
    }

    return new Response("Not Found", { status: 404, headers: corsHeaders });
  }
};
