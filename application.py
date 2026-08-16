"""Entrypoint.

The application itself lives in the ``app`` package; this module stays so that
``uvicorn application:app`` keeps working for existing deploys (including the
Hugging Face Space).
"""

from app.main import app

__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn

    from app.config import get_settings

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port)
