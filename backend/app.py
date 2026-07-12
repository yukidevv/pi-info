"""ラズパイ システムモニタリング API。

/            -> ダッシュボード (index.html)
/api/metrics -> 現在のメトリクスを JSON で返す
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from metrics import Sampler, collect

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
_sampler = Sampler(interval=1.0)


class _PollingFilter(logging.Filter):
    """高頻度ポーリングされる /api/metrics のアクセスログを抑制する。

    フロントは 1.5 秒ごとに /api/metrics を叩くため、記録すると1日で数万行に
    なる。起動ログやそれ以外のアクセスログは残す。
    """

    _SILENCED = ("/api/metrics",)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(path in message for path in self._SILENCED)


logging.getLogger("uvicorn.access").addFilter(_PollingFilter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    _sampler.start()
    yield
    _sampler.stop()


app = FastAPI(title="pi-info", lifespan=lifespan)


@app.get("/api/metrics")
async def api_metrics() -> JSONResponse:
    return JSONResponse(collect(_sampler))


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "index.html")


# その他の静的ファイル（あれば）
app.mount("/static", StaticFiles(directory=_FRONTEND_DIR), name="static")
