# image_utils.py
# Citizen complaint-image validation and storage for the waste-AI flow.
#
# Security rules:
#   - Formats: JPEG / PNG / WEBP ONLY (the exact set the AI's own mime map accepts).
#   - Client-supplied MIME is NOT trusted: content is validated by magic bytes,
#     and a declared MIME that contradicts the content is rejected.
#   - The size limit is enforced by the router BEFORE the body is read.
#   - Filenames are server-generated UUIDs; original filenames never touch the
#     filesystem path (no path traversal, no user-controlled paths).
#   - Stored images are separated from cleaner proof images (complaints/ subdir)
#     and served via the existing /uploads static mount.

import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
UPLOADS_DIR = Path(__file__).resolve().parent / "uploads"
COMPLAINT_IMAGE_DIR = UPLOADS_DIR / "complaints"
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB

# Declared MIME -> expected extension
MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
EXT_TO_MIME = {v: k for k, v in MIME_TO_EXT.items()}

# Error codes
ERR_IMAGE_REQUIRED = "IMAGE_REQUIRED"
ERR_IMAGE_EMPTY = "IMAGE_EMPTY"
ERR_IMAGE_TOO_LARGE = "IMAGE_TOO_LARGE"
ERR_IMAGE_UNSUPPORTED_TYPE = "IMAGE_UNSUPPORTED_TYPE"
ERR_IMAGE_MIME_MISMATCH = "IMAGE_MIME_MISMATCH"


def sniff_extension(head: bytes) -> str | None:
    """Detect the real file type from leading bytes: 'jpg' | 'png' | 'webp' | None."""
    if len(head) < 12:
        return None
    if head[:3] == b"\xff\xd8\xff":                      # JPEG: FF D8 FF
        return "jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":                 # PNG: 89 50 4E 47 0D 0A 1A 0A
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":    # WEBP: RIFF....WEBP
        return "webp"
    return None


def validate_image_upload(data: bytes | None, declared_mime: str | None) -> tuple[bool, str | None]:
    """Validate one uploaded image. Returns (ok, error_code). Never raises."""
    if data is None:
        return False, ERR_IMAGE_REQUIRED
    if len(data) == 0:
        return False, ERR_IMAGE_EMPTY
    if len(data) > MAX_IMAGE_BYTES:
        return False, ERR_IMAGE_TOO_LARGE

    sniffed = sniff_extension(data[:16])
    if sniffed is None:
        return False, ERR_IMAGE_UNSUPPORTED_TYPE

    if declared_mime is not None:
        expected = MIME_TO_EXT.get(declared_mime.strip().lower())
        if expected is None:
            return False, ERR_IMAGE_UNSUPPORTED_TYPE
        if expected != sniffed:
            # e.g. declared image/png but the bytes are JPEG — reject (422 upstream)
            return False, ERR_IMAGE_MIME_MISMATCH

    return True, None


def store_complaint_image(data: bytes, sniffed_ext: str) -> tuple[str, str]:
    """Persist one complaint image under uploads/complaints/ with a UUID name.

    Returns (image_url, mime_type). The URL follows the existing /uploads
    static-mount convention; filesystem paths are never exposed.
    Caller must have validated the data already (validate_image_upload).
    """
    COMPLAINT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"complaint_{uuid.uuid4().hex}.{sniffed_ext}"
    (COMPLAINT_IMAGE_DIR / filename).write_bytes(data)
    image_url = f"/uploads/complaints/{filename}"
    return image_url, EXT_TO_MIME[sniffed_ext]
