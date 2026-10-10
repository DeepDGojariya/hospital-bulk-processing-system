"""Serves the built React front end. The page only calls the public API."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import SettingsDep

router = APIRouter(include_in_schema=False)


@router.get("/")
async def index(settings: SettingsDep) -> FileResponse:
    page = settings.ui_dir / "index.html"
    if not page.is_file():
        raise HTTPException(
            503, "The UI has not been built. Run `npm install && npm run build` in frontend/."
        )
    return FileResponse(page)
