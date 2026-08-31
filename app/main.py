from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import get_settings
from app.firebase import initialize_firebase
from app.routes import router as api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    initialize_firebase()
    yield
    # Shutdown (if needed)


settings = get_settings()

app = FastAPI(
    title="ThreadOS AI Agent API",
    description="Backend API for ThreadOS AI Customer Service & Commerce Agent",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "threados-ai-agent"}


@app.get("/")
async def root():
    return {
        "service": "ThreadOS AI Agent API",
        "version": "0.1.0",
        "docs": "/docs"
    }