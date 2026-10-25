"""Public homepage content and validated administrator-managed images."""
import fcntl
import io
import json
import os
import re
import tempfile
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .auth import admin
from .config import settings

router = APIRouter(prefix="/api/v1/website", tags=["Website"])
SLOTS = ("hero", "about", "work-1", "work-2", "work-3", "work-4", "film-1", "film-2")
MAX_UPLOAD = 5 * 1024 * 1024
MAX_STORED = 2 * 1024 * 1024
MAX_PIXELS = 20_000_000

class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Literal["about", "work", "films", "services", "contact"]
    eyebrow: str = Field(max_length=80)
    title: str = Field(min_length=1, max_length=160)
    text: str = Field(max_length=2000)
    visible: bool = True

class Card(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot: Literal["work-1", "work-2", "work-3", "work-4", "film-1", "film-2"]
    title: str = Field(min_length=1, max_length=120)
    category: str = Field(max_length=100)
    description: str = Field(max_length=1500)
    link: str = Field(default="", max_length=500)
    portfolio_section_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]+$", max_length=80)

    @field_validator("link")
    @classmethod
    def valid_link(cls, value):
        if value and not re.fullmatch(r"https://(?:www\.)?(?:youtube\.com/watch\?v=[\w-]+|youtu\.be/[\w-]+|vimeo\.com/\d+)", value):
            raise ValueError("Use a YouTube or Vimeo video URL")
        return value

class Content(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand: str = Field(min_length=1, max_length=60)
    tagline: str = Field(max_length=120)
    hero_title: str = Field(min_length=1, max_length=180)
    hero_text: str = Field(max_length=500)
    email: str = Field(default="", max_length=150)
    phone: str = Field(default="", max_length=40)
    location: str = Field(default="", max_length=120)
    whatsapp: str = Field(default="917909058028", pattern=r"^[1-9][0-9]{7,14}$")
    accent: str = "#8E43F0"
    accent_dark: str = "#6300E2"
    sections: list[Section] = Field(min_length=5, max_length=5)
    cards: list[Card] = Field(min_length=6, max_length=6)
    services: list[str] = Field(min_length=1, max_length=6)

    @field_validator("accent", "accent_dark")
    @classmethod
    def valid_colour(cls, value):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("Use a six-digit hex colour")
        return value

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if value and not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value):
            raise ValueError("Enter a valid email address")
        return value

    @field_validator("phone")
    @classmethod
    def valid_phone(cls, value):
        if value and not re.fullmatch(r"[+\d ()-]{5,40}", value):
            raise ValueError("Enter a phone number")
        return value

    @field_validator("sections")
    @classmethod
    def fixed_sections(cls, value):
        if {s.id for s in value} != {"about", "work", "films", "services", "contact"}:
            raise ValueError("Keep the five existing sections")
        return value

    @field_validator("cards")
    @classmethod
    def fixed_cards(cls, value):
        if {c.slot for c in value} != set(SLOTS[2:]):
            raise ValueError("Keep the six existing portfolio slots")
        return value

    @field_validator("services")
    @classmethod
    def bounded_services(cls, value):
        if any(not v.strip() or len(v) > 100 for v in value):
            raise ValueError("Service names must contain 1–100 characters")
        return value

DEFAULT = Content(
    brand="NialTech", tagline="A creative perspective.",
    hero_title="Good stories deserve\na different perspective.",
    hero_text="Design. Imagery. Motion. Digital experiences with a little more feeling.",
    sections=[
        Section(id="about", eyebrow="THE WAY WE SEE IT", title="A little imagination.\nA lasting impression.", text="We bring design, imagery and technology together. From the first idea to the final frame, our focus is on thoughtful details and work that feels unmistakably yours."),
        Section(id="work", eyebrow="A CLOSER LOOK", title="Made to be remembered.", text="A place for our visual explorations, projects and the ideas behind them."),
        Section(id="films", eyebrow="STORIES IN MOTION", title="Every frame has a feeling.", text="Motion graphics, films and edits that give an idea a life of its own."),
        Section(id="services", eyebrow="WHAT WE DO", title="One idea.\nMany possibilities.", text="From a fresh visual identity to a considered digital presence, find the right creative direction for your next chapter."),
        Section(id="contact", eyebrow="LET’S CREATE SOMETHING", title="Your next chapter\nstarts with a hello.", text="Have an idea, a brief, or just a question? We’d love to hear what you have in mind."),
    ],
    cards=[Card(slot=f"work-{i}", title=t, category=c, description="Portfolio preview — replace this image and description with your own project before publishing.") for i,t,c in [(1,"A study in light","PHOTO EDITING"),(2,"Beyond the ordinary","GRAPHIC DESIGN"),(3,"A new point of view","WEB DEVELOPMENT"),(4,"The art of a moment","VISUAL STORYTELLING")]] + [Card(slot="film-1", title="A feeling, in motion", category="MOTION GRAPHICS", description="Film preview — add your project description and a YouTube or Vimeo link."), Card(slot="film-2", title="The spaces between", category="VIDEO EDITING", description="Film preview — add your project description and a YouTube or Vimeo link.")],
    services=["Graphic design", "Photo editing", "Motion graphics", "Web development", "Video editing"],
)

def root():
    path = Path(settings.WEBSITE_DATA_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path

@contextmanager
def locked():
    # Cross-process lock: edits and replacements serialize even with multiple API workers.
    with (root() / ".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)

def atomic_write(path, data):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".replace-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def read_content():
    path = root() / "content.json"
    return Content.model_validate_json(path.read_text()) if path.exists() else DEFAULT.model_copy(deep=True)

def public_content():
    result = read_content().model_dump()
    result["images"] = {slot: f"/api/v1/website/assets/{slot}?v={(root() / (slot + '.webp')).stat().st_mtime_ns}" for slot in SLOTS if (root() / (slot + ".webp")).exists()}
    result["limits"] = {"slots": len(SLOTS), "upload_mb": 5, "stored_image_mb": 2, "total_image_mb": None, "portfolio_photo_count": None, "max_dimension": 2400}
    return result

@router.get("")
def get_content():
    with locked():
        return public_content()

@router.patch("")
def update_content(data: Content, _=Depends(admin)):
    with locked():
        atomic_write(root() / "content.json", data.model_dump_json(indent=2).encode())
        return public_content()

@router.get("/assets/{slot}")
def image(slot: str):
    if slot not in SLOTS:
        raise HTTPException(404, "Image slot not found")
    path = root() / (slot + ".webp")
    if not path.is_file():
        raise HTTPException(404, "No image in this slot")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})

@router.post("/assets/{slot}")
def replace_image(slot: str, file: UploadFile = File(...), _=Depends(admin)):
    if slot not in SLOTS:
        raise HTTPException(404, "Image slot not found")
    encoded = encode_image(file)
    with locked():
        atomic_write(root() / (slot + ".webp"), encoded)
        return public_content()


def encode_image(file: UploadFile):
    raw = file.file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "Image must be 5 MB or smaller")
    # Never trust filename/MIME type. Decode, cap pixels and re-encode to strip metadata.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise HTTPException(415, "Use a JPEG, PNG or WebP image")
                if source.width * source.height > MAX_PIXELS or source.width < 1 or source.height < 1:
                    raise HTTPException(413, "Image must be at most 20 megapixels")
                if getattr(source, "is_animated", False):
                    raise HTTPException(415, "Use a still image")
                source.thumbnail((2400, 2400))
                normalized = ImageOps.exif_transpose(source).convert("RGB")
                output = io.BytesIO()
                normalized.save(output, "WEBP", quality=82, method=4)
                encoded = output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise HTTPException(415, "Cannot read this image; use a valid JPEG, PNG or WebP")
    if len(encoded) > MAX_STORED:
        raise HTTPException(413, "Optimized image exceeds 2 MB; choose a simpler or smaller image")
    return encoded
