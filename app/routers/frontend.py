import os
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["frontend"])

@router.get("/")
def get_dashboard():
    """Serves the dashboard single-page application."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "templates", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)
