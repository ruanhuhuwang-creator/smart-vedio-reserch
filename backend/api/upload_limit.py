from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class UploadLimitMiddleware:
    """Bound the raw multipart body before Starlette spools it to disk."""
    def __init__(self, app, max_bytes):
        self.app = app
        self.limit = max_bytes + 64 * 1024

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"].rstrip("/") != "/api/videos":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Content-Length 无效"}, status_code=400)(scope, receive, send)
        if declared < 0 or declared > self.limit:
            return await JSONResponse({"detail": "上传请求超过大小限制"}, status_code=413)(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    raise HTTPException(413, "上传请求超过大小限制")
            return message

        await self.app(scope, limited_receive, send)
