from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Totalome Backend", version="0.1.0")

# Allow your frontend to call this API (adjust origins later)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "Totalome backend is running!", "docs": "/docs", "health": "/health"}

@app.get("/health")
def health():
    return {"ok": True}
