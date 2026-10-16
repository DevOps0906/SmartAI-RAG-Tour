"""FastAPI 앱. 실행: uvicorn src.web.app:app (그래프/체크포인터는 runtime.get_runtime 이 처음 필요할 때 만든다)"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import ON_VERCEL
from src.destinations import supported_destinations
from src.rag.text import clean_snippet
from src.trip import duration_label, md as trip_md, md_wd as trip_md_wd
from src.web.fmt import kst_stamp
from src.web.runtime import get_runtime

BASE = Path(__file__).parent
log = logging.getLogger(__name__)

templates = Jinja2Templates(directory=str(BASE / "templates"))
# 정적 파일 캐시 무효화용 버전(파일 수정 시각)
def _asset_v(name: str) -> int:
    try:
        return int((BASE / "static" / name).stat().st_mtime)
    except OSError:   # 파일이 없어도 페이지 전체가 500 이 되지 않게 (캐시 무효화만 포기)
        return 0


templates.env.globals["asset_v"] = _asset_v
templates.env.filters["comma"] = lambda v: f"{v:,.0f}" if isinstance(v, (int, float)) else v
templates.env.filters["snippet"] = clean_snippet
templates.env.filters["kst"] = kst_stamp
templates.env.filters["md"] = trip_md
templates.env.filters["md_wd"] = trip_md_wd
templates.env.globals["duration_label"] = duration_label
templates.env.globals["nav_destinations"] = supported_destinations   # 공통 GNB 의 여행지 메뉴


@asynccontextmanager
async def lifespan(app: FastAPI):
    if ON_VERCEL and not os.environ.get("WEB_SECRET"):
        log.warning("WEB_SECRET 이 설정되지 않아 공개된 기본 서명 키를 씁니다. Vercel 환경변수에 WEB_SECRET 을 넣어 주세요.")
    get_runtime(app)
    yield
    conn = getattr(app.state.checkpointer, "conn", None)
    if conn is not None:
        conn.close()


app = FastAPI(title="Smart Travel", lifespan=lifespan)
app.state.templates = templates
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

from src.web.routes import router  # noqa: E402  (순환 import 방지)

app.include_router(router)
