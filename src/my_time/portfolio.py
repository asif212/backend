"""Nested public portfolios with an administrator-managed, uncapped photo library."""
import json
import re
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from .auth import admin
from .website import root, locked, atomic_write, encode_image

router = APIRouter(prefix="/api/v1/website/portfolio", tags=["Portfolio"])
DEFAULT_SECTIONS = [("graphic-design", "Graphic Design"), ("photo-editing", "Photo Editing"), ("motion-graphics", "Motion Graphics"), ("website-development", "Web Development"), ("video-editing", "Video Editing")]

class SectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=3000)
    parent_id: str | None = None
    cover_id: str | None = None

def read():
    path = root() / "portfolio.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"sections": [{"id": id, "title": title, "description": "", "parent_id": None, "cover_id": None} for id, title in DEFAULT_SECTIONS], "photos": []}

def save(data):
    atomic_write(root() / "portfolio.json", json.dumps(data, ensure_ascii=False).encode())

def section(data, id):
    found = next((s for s in data["sections"] if s["id"] == id), None)
    if found is None:
        raise HTTPException(404, "Portfolio section not found")
    return found

def public(data):
    return {"sections": data["sections"], "photos": [{**p, "url": f"/api/v1/website/portfolio/photos/{p['id']}"} for p in data["photos"]]}

def validate(data, value, id=None):
    if value.parent_id:
        parent = section(data, value.parent_id)
        while parent:
            if parent["id"] == id:
                raise HTTPException(422, "A section cannot be its own parent or a child of its descendants")
            parent = section(data, parent["parent_id"]) if parent["parent_id"] else None
    if value.cover_id and not any(p["id"] == value.cover_id for p in data["photos"]):
        raise HTTPException(422, "Choose a cover from the uploaded photos")

def assets():
    path = root() / "portfolio_assets"
    path.mkdir(exist_ok=True)
    return path

@router.get("")
def get_portfolio():
    with locked():
        return public(read())

@router.post("/sections", status_code=201)
def create_section(value: SectionInput, _=Depends(admin)):
    with locked():
        data = read()
        validate(data, value)
        data["sections"].append({"id": uuid4().hex, **value.model_dump()})
        save(data)
        return public(data)

@router.patch("/sections/{id}")
def edit_section(id: str, value: SectionInput, _=Depends(admin)):
    with locked():
        data = read()
        node = section(data, id)
        validate(data, value, id)
        node.update(value.model_dump())
        save(data)
        return public(data)

@router.delete("/sections/{id}")
def delete_section(id: str, _=Depends(admin)):
    with locked():
        data = read()
        section(data, id)
        removed = {id}
        while True:
            descendants = {s["id"] for s in data["sections"] if s["parent_id"] in removed}
            if descendants <= removed:
                break
            removed |= descendants
        deleted_photos = [p for p in data["photos"] if p["section_id"] in removed]
        photos = {p["id"] for p in deleted_photos}
        data["sections"] = [s for s in data["sections"] if s["id"] not in removed]
        data["photos"] = [p for p in data["photos"] if p["id"] not in photos]
        for s in data["sections"]:
            if s["cover_id"] in photos:
                s["cover_id"] = None
        save(data)
        for photo in deleted_photos:
            photo_path(photo).unlink(missing_ok=True)
        return public(data)

@router.post("/sections/{id}/photos", status_code=201)
def upload_photo(id: str, file: UploadFile = File(...), _=Depends(admin)):
    # Validate ownership/target before decoding. Recheck after acquiring the write lock.
    with locked():
        section(read(), id)
    encoded = encode_image(file)
    photo_id = uuid4().hex
    name = Path(file.filename or "Photo").name[:200]
    with locked():
        data = read()
        node = section(data, id)
        path = assets() / (photo_id + ".webp")
        atomic_write(path, encoded)
        try:
            data["photos"].append({"id": photo_id, "section_id": id, "name": name})
            if node["cover_id"] is None:
                node["cover_id"] = photo_id
            save(data)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return public(data)

@router.get("/photos/{id}")
def get_photo(id: str):
    if not re.fullmatch(r"[0-9a-f]{32}", id):
        raise HTTPException(404, "Photo not found")
    with locked():
        photo = next((p for p in read()["photos"] if p["id"] == id), None)
        if not photo:
            raise HTTPException(404, "Photo not found")
        path = photo_path(photo)
    if not path.is_file():
        raise HTTPException(404, "Photo not found")
    mime = "image/gif" if path.suffix == ".gif" else "image/webp"
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"})


def photo_path(photo):
    extension = ".gif" if photo.get("extension") == ".gif" else ".webp"
    return assets() / (photo["id"] + extension)

@router.delete("/photos/{id}")
def delete_photo(id: str, _=Depends(admin)):
    with locked():
        data = read()
        if not any(p["id"] == id for p in data["photos"]):
            raise HTTPException(404, "Photo not found")
        removed_photo = next(p for p in data["photos"] if p["id"] == id)
        data["photos"] = [p for p in data["photos"] if p["id"] != id]
        for s in data["sections"]:
            if s["cover_id"] == id:
                s["cover_id"] = None
        save(data)
        photo_path(removed_photo).unlink(missing_ok=True)
        return public(data)
