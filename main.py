from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager

from db.database import init_db, close_db
from core.meta_client import meta_client
from core.config import settings
from routers import webhook, conversations, messages, ws

import structlog

logger = structlog.get_logger()


EXEMPT_PATHS = {"/", "/api/health", "/webhook/whatsapp", "/docs", "/openapi.json", "/redoc"}


class TokenAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path in EXEMPT_PATHS or path.startswith("/webhook"):
            return await call_next(request)

        if not settings.DASHBOARD_TOKEN:
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if auth == f"Bearer {settings.DASHBOARD_TOKEN}":
            return await call_next(request)

        return Response(status_code=401, content="Unauthorized")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("db_initialized", path=settings.DB_PATH)
    logger.info(
        "settings_loaded",
        llm_provider=settings.LLM_PROVIDER,
        llm_model=settings.LLM_MODEL,
        llm_base_url=settings.LLM_BASE_URL,
        llm_key_set=bool(settings.LLM_API_KEY and not settings.LLM_API_KEY.startswith("nvapi-REPLACE")),
        meta_api_url=settings.META_API_URL,
        meta_token_set=bool(settings.WHATSAPP_ACCESS_TOKEN),
        meta_token_prefix=settings.WHATSAPP_ACCESS_TOKEN[:10] + "..." if settings.WHATSAPP_ACCESS_TOKEN else "EMPTY",
        phone_number_id=settings.WHATSAPP_PHONE_NUMBER_ID,
        env_file=settings.Config.env_file,
    )
    yield
    await meta_client.close()
    await close_db()
    logger.info("shutdown_complete")


app = FastAPI(
    title="Hermes WhatsApp HITL Gateway",
    description="Custom Gateway Meta Cloud API con Human-in-the-Loop",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(TokenAuthMiddleware)

cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook.router)
app.include_router(conversations.router)
app.include_router(messages.router)
app.include_router(ws.router)


@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Hermes WhatsApp Gateway</title>
    <style>
    body { background: #111; color: #eee; font-family: system-ui; padding: 40px; }
    a { color: #4CAF50; }
    .container { max-width: 800px; margin: 0 auto; }
    .endpoint { background: #1f2937; padding: 12px; margin: 8px 0; border-radius: 8px; }
    .method { color: #4CAF50; font-weight: bold; }
    code { background: #374151; padding: 2px 6px; border-radius: 4px; }
    </style>
    </head>
    <body>
    <div class="container">
    <h1>Hermes WhatsApp HITL Gateway</h1>
    <p>Custom Gateway Meta Cloud API + Human-in-the-Loop Dashboard</p>

    <h2>Endpoints</h2>
<div class="endpoint"><span class="method">GET</span> <code>/webhook/whatsapp</code> — Meta webhook verification</div>
            <div class="endpoint"><span class="method">POST</span> <code>/webhook/whatsapp</code> — Meta webhook receiver</div>
    <div class="endpoint"><span class="method">GET</span> <code>/api/conversations</code> — List all conversations</div>
    <div class="endpoint"><span class="method">GET</span> <code>/api/conversations/{phone}</code> — Get conversation detail</div>
    <div class="endpoint"><span class="method">POST</span> <code>/api/conversations/state</code> — Update conversation state</div>
    <div class="endpoint"><span class="method">POST</span> <code>/api/conversations/{phone}/reset-unread</code> — Reset unread count</div>
    <div class="endpoint"><span class="method">GET</span> <code>/api/messages/{phone}</code> — Get message history</div>
    <div class="endpoint"><span class="method">POST</span> <code>/api/messages/send</code> — Send manual message</div>
    <div class="endpoint"><span class="method">WS</span> <code>/ws</code> — WebSocket real-time events</div>

    <h2>States</h2>
    <ul>
    <li><strong>BOT_ACTIVE</strong> — Bot handles everything</li>
    <li><strong>PENDING_APPROVAL</strong> — Escalated, waiting for human review</li>
    <li><strong>HUMAN_ONLY</strong> — Human takes over completely</li>
    </ul>

    <p>Dashboard: <a href="http://localhost:3000" target="_blank">http://localhost:3000</a></p>
    <p>API Docs: <a href="/docs" target="_blank">/docs</a></p>
    <p>Health: <a href="/api/health" target="_blank">/api/health</a></p>
    </div>
    </body>
    </html>
    """


@app.get("/api/health")
async def health_check():
    meta_health = await meta_client.health_check()
    llm_key_valid = bool(settings.LLM_API_KEY and not settings.LLM_API_KEY.startswith("nvapi-REPLACE"))
    return {
        "status": "ok" if meta_health["connected"] and llm_key_valid else "degraded",
        "meta_api": {
            "connected": meta_health["connected"],
            "status_code": meta_health["status_code"],
            "error": meta_health["error"],
            "api_version": settings.META_API_URL.split("/")[-1],
            "phone_number_id": settings.WHATSAPP_PHONE_NUMBER_ID,
            "token_set": bool(settings.WHATSAPP_ACCESS_TOKEN),
            "token_prefix": settings.WHATSAPP_ACCESS_TOKEN[:10] + "..." if settings.WHATSAPP_ACCESS_TOKEN else "EMPTY",
        },
        "llm": {
            "available": llm_key_valid,
            "provider": settings.LLM_PROVIDER,
            "model": settings.LLM_MODEL,
            "base_url": settings.LLM_BASE_URL,
            "api_key_set": llm_key_valid,
        },
        "db_path": settings.DB_PATH,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT, reload=True)
