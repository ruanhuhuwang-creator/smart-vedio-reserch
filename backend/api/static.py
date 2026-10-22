"""Optional production UI, mounted after all API/documentation routes."""
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def serve_frontend(application, directory: Path):
    root = directory.resolve()
    if not (root / "index.html").is_file() or not (root / "assets").is_dir():
        raise RuntimeError(f"Vue 生产资源不完整：{root}")
    application.mount("/assets", StaticFiles(directory=root / "assets"), name="frontend-assets")

    @application.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.split("/", 1)[0] in {"api", "health", "docs", "redoc", "openapi.json"}:
            raise HTTPException(404, "接口不存在")
        candidate = (root / path).resolve()
        if not candidate.is_relative_to(root):
            raise HTTPException(404, "资源不存在")
        if candidate.is_file():
            return FileResponse(candidate)
        if Path(path).suffix:
            raise HTTPException(404, "资源不存在")
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})
