from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ACC chatbot API routes
from app.api.routes.chat import router as chat_router
from app.api.routes.cdr import router as cdr_router
from app.api.routes.relationship import router as relationship_router

# Authentication route from the frontend/backend integration
from app.routes.auth import router as auth_router


app = FastAPI(
    title="ACC Investigation Support System",
    description="Backend API for the ACC investigation support chatbot",
    version="1.0.0",
)

# Allow requests from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "ACC Investigation Chatbot API is running"}


# Register all routers
app.include_router(chat_router)
app.include_router(cdr_router)
app.include_router(relationship_router)
app.include_router(auth_router)
