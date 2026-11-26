"""ASGI entrypoint: ``uvicorn app.main:app``."""
from app.bootstrap.api import create_app
from app.platform.config import settings

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=True if settings.ENVIRONMENT == "development" else False
    )
