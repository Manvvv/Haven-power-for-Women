"""LSB steganography service for HAVEN covert SOS.

The covert flow hides a distress message in the least-significant bit of every
RGB channel byte of a *lossless* PNG. HAVEN is multilingual (Hindi/Devanagari,
Hinglish, emoji), so the payload MUST be UTF-8 safe — the previous codec packed
`ord(c)` into 8 bits, which silently corrupts any codepoint > 255.

Wire format (identical on encode and decode — do not change one side only):

    ┌──────────┬──────────────┬──────────────────┬────────────┐
    │  MAGIC   │  LENGTH (u32)│  UTF-8 PAYLOAD   │ CRC32 (u32)│
    │ b"HVN1"  │  big-endian  │  LENGTH bytes    │ big-endian │
    │ 4 bytes  │  4 bytes     │  variable        │ 4 bytes    │
    └──────────┴──────────────┴──────────────────┴────────────┘

Bits are laid out MSB-first (np.unpackbits / np.packbits) across the flattened
RGB LSBs. The MAGIC lets the decoder tell "no HAVEN payload" from "corrupted
HAVEN payload"; the CRC32 + UTF-8 validation catch bit rot (e.g. a JPEG/WebP
recompression that destroyed the LSBs) instead of returning garbage.

This module NEVER fakes success: if a message does not fit, encode raises
MessageTooLargeForImage rather than returning an unmodified image.
"""
import io
import struct
import zlib
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("haven_backend")

MAGIC = b"HVN1"
_HEADER_BYTES = len(MAGIC) + 4      # magic + u32 length
_FOOTER_BYTES = 4                   # u32 CRC32
_OVERHEAD_BYTES = _HEADER_BYTES + _FOOTER_BYTES  # 12 bytes = 96 bits
# Lossy formats destroy LSBs on decompression; refuse rather than emit garbage.
_LOSSY_FORMATS = {"JPEG", "JPG", "WEBP", "GIF"}


class StegoError(Exception):
    """Base class for steganography failures surfaced to the API layer."""


class MessageTooLargeForImage(StegoError):
    """Raised when the payload cannot fit in the image's LSB capacity."""


class DecodeStatus:
    """Structured decode outcomes — the decoder distinguishes each case."""
    OK = "OK"
    NO_PAYLOAD = "NO_PAYLOAD"              # no HAVEN magic present
    CORRUPTED_PAYLOAD = "CORRUPTED_PAYLOAD"  # magic present, CRC/length/UTF-8 bad
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"  # lossy input can't carry LSBs
    INVALID_IMAGE = "INVALID_IMAGE"        # not a parseable image


@dataclass
class StegoDecodeResult:
    """Result of a decode attempt. `message` is set only when status == OK."""
    status: str
    message: Optional[str] = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == DecodeStatus.OK


def _build_payload(message: str) -> bytes:
    """Serialize a message into the HAVEN wire format (UTF-8 safe)."""
    utf8 = message.encode("utf-8")
    crc = zlib.crc32(utf8) & 0xFFFFFFFF
    return MAGIC + struct.pack(">I", len(utf8)) + utf8 + struct.pack(">I", crc)


def image_lsb_capacity_bytes(image_bytes: bytes) -> int:
    """Max payload bytes (incl. 12-byte overhead) the image's LSBs can hold."""
    from PIL import Image
    import numpy as np
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return int(np.array(img, dtype=np.uint8).size) // 8


def encode_message_in_image(image_bytes: bytes, message: str) -> bytes:
    """Embed `message` into `image_bytes` via LSB steganography; return PNG bytes.

    Always normalizes to a lossless RGB PNG (JPEG/WebP would destroy the LSBs).
    Raises MessageTooLargeForImage if the payload does not fit — it NEVER returns
    an unmodified image and calls it success.
    """
    from PIL import Image
    import numpy as np

    # Normalize to RGB first. A lossy source is fine as the *carrier* because we
    # re-save as PNG here; the danger is only lossy re-encoding AFTER embedding.
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img_array = np.array(img, dtype=np.uint8)
    flat = img_array.flatten()

    payload = _build_payload(message)
    payload_bits = np.unpackbits(np.frombuffer(payload, dtype=np.uint8))  # MSB-first

    if payload_bits.size > flat.size:
        capacity = flat.size // 8
        raise MessageTooLargeForImage(
            f"Message needs {len(payload)} bytes but image holds {capacity}."
        )

    n = payload_bits.size
    flat[:n] = (flat[:n] & 0xFE) | payload_bits
    result_img = Image.fromarray(flat.reshape(img_array.shape), "RGB")

    output = io.BytesIO()
    result_img.save(output, format="PNG")  # MUST stay lossless PNG
    return output.getvalue()


def decode_message(image_bytes: bytes) -> StegoDecodeResult:
    """Extract a HAVEN LSB payload, distinguishing every failure mode.

    Returns a StegoDecodeResult whose status is one of DecodeStatus.* — never a
    bare "No hidden message found" string for unrelated failures.
    """
    from PIL import Image, UnidentifiedImageError
    import numpy as np

    try:
        img = Image.open(io.BytesIO(image_bytes))
    except (UnidentifiedImageError, Exception):
        return StegoDecodeResult(DecodeStatus.INVALID_IMAGE,
                                 detail="Image could not be parsed.")

    # A lossy format cannot faithfully carry LSBs; reject instead of returning
    # garbage that might look like (or falsely fail to look like) a payload.
    fmt = (img.format or "").upper()
    if fmt in _LOSSY_FORMATS:
        return StegoDecodeResult(
            DecodeStatus.UNSUPPORTED_FORMAT,
            detail=f"{fmt} is lossy; hidden data requires a lossless PNG.",
        )

    try:
        img = img.convert("RGB")
        lsb = (np.array(img, dtype=np.uint8).flatten() & 1).astype(np.uint8)
    except Exception:
        return StegoDecodeResult(DecodeStatus.INVALID_IMAGE,
                                 detail="Image pixels could not be read.")

    total_bits = int(lsb.size)
    if total_bits < _OVERHEAD_BYTES * 8:
        return StegoDecodeResult(DecodeStatus.NO_PAYLOAD,
                                 detail="Image too small to contain a payload.")

    # Header: magic (4B) + length (4B).
    header = np.packbits(lsb[:_HEADER_BYTES * 8]).tobytes()
    if header[:4] != MAGIC:
        return StegoDecodeResult(DecodeStatus.NO_PAYLOAD,
                                 detail="No HAVEN payload marker found.")

    (length,) = struct.unpack(">I", header[4:8])
    needed_bits = (_HEADER_BYTES + length + _FOOTER_BYTES) * 8
    if needed_bits > total_bits:
        # Magic matched but the declared length can't fit — the bits are damaged.
        return StegoDecodeResult(DecodeStatus.CORRUPTED_PAYLOAD,
                                 detail="Declared payload length exceeds image capacity.")

    body = np.packbits(lsb[_HEADER_BYTES * 8: needed_bits]).tobytes()
    payload = body[:length]
    (crc_stored,) = struct.unpack(">I", body[length:length + 4])
    if (zlib.crc32(payload) & 0xFFFFFFFF) != crc_stored:
        return StegoDecodeResult(DecodeStatus.CORRUPTED_PAYLOAD,
                                 detail="Checksum mismatch — hidden data is damaged.")

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return StegoDecodeResult(DecodeStatus.CORRUPTED_PAYLOAD,
                                 detail="Payload is not valid UTF-8 text.")

    return StegoDecodeResult(DecodeStatus.OK, message=text)


def decode_message_from_image(image_bytes: bytes) -> str:
    """Backwards-compatible string API.

    Returns the decoded message on success, else "No hidden message found".
    New callers should prefer decode_message() for structured error handling.
    """
    return decode_message(image_bytes).message or "No hidden message found"
