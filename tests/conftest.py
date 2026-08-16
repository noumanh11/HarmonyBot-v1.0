import os
import sys
from pathlib import Path

# Tests run offline against a stub model: no dataset download, no HF calls.
os.environ["ENABLE_RETRIEVAL"] = "false"
os.environ.setdefault("HF_TOKEN", "test-token")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


class StubLLM:
    """Stands in for the Hugging Face client."""

    def __init__(self, chunks=("Hello ", "there."), error: Exception | None = None):
        self.chunks = chunks
        self.error = error
        self.last_messages = None

    async def stream(self, messages):
        self.last_messages = messages
        if self.error:
            raise self.error
        for chunk in self.chunks:
            yield chunk

    async def complete(self, messages):
        return "".join([c async for c in self.stream(messages)])

    async def aclose(self):
        pass


@pytest.fixture
def stub() -> StubLLM:
    return StubLLM()


@pytest.fixture
def client(stub):
    app = create_app()
    with TestClient(app) as c:
        # Swap the real client in after startup has wired everything together.
        c.app.state.llm = stub
        c.app.state.chat_service._llm = stub
        yield c
