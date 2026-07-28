from fastapi import FastAPI

app = FastAPI(title="Neon Backgammon Tournament")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
