from __future__ import annotations
import httpx
from app.core.config import get_settings

class CVGateway:
    async def classify(self, image_ref: str | None = None) -> dict:
        raise NotImplementedError

class MockCVGateway(CVGateway):
    def __init__(self, result: dict | None = None):
        self.result = result or {'core_type':'CORE-A','quantity':30,'confidence':0.96,'status':'ACCEPTED'}
    async def classify(self, image_ref: str | None = None) -> dict:
        return dict(self.result)

class HttpCVGateway(CVGateway):
    async def classify(self, image_ref: str | None = None) -> dict:
        base = get_settings().cv_base_url
        if not base: raise RuntimeError('CV_BASE_URL not configured')
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f'{base.rstrip("/")}/classify', json={'image_ref': image_ref})
            r.raise_for_status(); return r.json()
