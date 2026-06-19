from aiohttp import web
import os
import threading

def run_health_check():
    async def handle(request):
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_get("/", handle)
    port = int(os.environ.get("PORT", 8080))
    web.run_app(app, host="0.0.0.0", port=port)

def start_health_check():
    threading.Thread(target=run_health_check, daemon=True).start()
