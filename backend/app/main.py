from fastapi import FastAPI

from app.api.routes.chat import router as chat_router
from app.api.routes.cdr import router as cdr_router
from app.api.routes.relationship import router as relationship_router


app = FastAPI(
    title="ACC Investigation Chatbot API",
    description="Backend API for the ACC RAG-based chatbot",
    version="0.1.0"
)


@app.get("/")
async def root():
    return {
        "message": "ACC Chatbot Backend is running"
    }

app.include_router(chat_router)
app.include_router(cdr_router)
app.include_router(relationship_router)