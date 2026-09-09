"""CS 첨부파일 비공개 저장 헬퍼 (요구사항 10·21).

기존 image_service.save_upload 은 /static 공개 URL을 반환하므로 '권한 없는 URL 직접접근 차단'
요구를 못 지킨다. CS 첨부는 /static 밖 비공개 디렉터리에 저장하고, 인증 라우트를 통해서만
스트리밍한다. 이미지/영상/문서를 지원하며 원본 그대로 저장한다(재인코딩 없음).
"""
import uuid
from pathlib import Path
from fastapi import UploadFile
from app.cs import constants as C

# /static 밖 — 웹으로 직접 서빙되지 않는 비공개 저장소
PRIVATE_ROOT = Path("private_uploads/cs")

ALL_ALLOWED_EXTS = C.CS_IMAGE_EXTS | C.CS_VIDEO_EXTS | C.CS_DOC_EXTS


def _ext(filename: str) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def _kind(ext: str) -> str:
    if ext in C.CS_IMAGE_EXTS:
        return "image"
    if ext in C.CS_VIDEO_EXTS:
        return "video"
    return "file"


def save_cs_file(file: UploadFile, company_id: int, cs_id: str, allowed: set | None = None) -> dict | None:
    """파일 1개를 비공개 저장하고 CSAttachment 필드 dict 반환. 위반 시 ValueError.

    allowed: 허용 확장자 집합 제한(예: 이미지 전용). None 이면 이미지+영상+문서 전체 허용.
    """
    if not file or not file.filename:
        return None
    ext = _ext(file.filename)
    if ext in C.CS_BLOCKED_EXTS:
        raise ValueError("실행파일 등 허용되지 않는 형식입니다")
    allow = allowed if allowed is not None else ALL_ALLOWED_EXTS
    if ext not in allow:
        raise ValueError("허용되지 않는 파일 형식입니다")

    data = file.file.read()
    if not data:
        return None
    if len(data) > C.CS_MAX_FILE_SIZE:
        raise ValueError("파일 용량이 너무 큽니다 (최대 20MB)")

    dest_dir = PRIVATE_ROOT / str(company_id) / cs_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
    path = dest_dir / stored_name
    path.write_bytes(data)

    return {
        "stored_path": str(path),
        "file_name": file.filename,
        "file_type": _kind(ext),
        "content_type": file.content_type or "application/octet-stream",
        "size": len(data),
    }


def save_cs_image(file: UploadFile, company_id: int, cs_id: str) -> dict | None:
    """이미지 전용 래퍼 (등록 폼 사진 첨부용)."""
    return save_cs_file(file, company_id, cs_id, allowed=C.CS_IMAGE_EXTS)
