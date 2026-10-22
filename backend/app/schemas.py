"""Pydantic 输入输出结构。错误统一返回 {"error":{"code","message"}}。"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class Canvas(BaseModel):
    w: int = Field(1080, ge=64, le=8192)
    h: int = Field(1080, ge=64, le=8192)


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    canvas: Canvas = Field(default_factory=Canvas)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)


class Project(BaseModel):
    id: str
    name: str
    canvas: Dict[str, int]
    created_at: str
    updated_at: str


class Asset(BaseModel):
    id: str
    project_id: str
    kind: str  # original | matting | generated
    filename: str
    path: str
    width: Optional[int] = None
    height: Optional[int] = None
    sha256: Optional[str] = None
    thumb_path: Optional[str] = None
    created_at: str


class Layer(BaseModel):
    id: str
    project_id: str
    type: Literal["image", "text", "shape"]
    name: str = ""
    z: int = 0
    x: float = 0
    y: float = 0
    w: float = 0
    h: float = 0
    rotation: float = 0
    opacity: float = 1.0
    visible: bool = True
    locked: bool = False
    blend: str = "normal"
    content: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class LayersReplace(BaseModel):
    layers: List[Layer]


class GenParams(BaseModel):
    mode: Literal["txt2img", "img2img", "inpaint", "control_bg", "matting"] = "txt2img"
    prompt: str = Field("", max_length=2000)
    confirm_cost: bool = False
    negative_prompt: str = ""
    width: int = Field(1024, ge=64, le=8192)
    height: int = Field(1024, ge=64, le=8192)
    steps: int = Field(28, ge=10, le=50)
    cfg: float = Field(7.0, ge=1.0, le=20.0)
    seed: int = -1
    num_images: int = Field(1, ge=1, le=4)
    ref_asset_id: Optional[str] = None
    mask_asset_id: Optional[str] = None
    ctrl_type: Optional[str] = None
    ctrl_strength: Optional[float] = None


class Generation(BaseModel):
    id: str
    project_id: str
    params: Dict[str, Any]
    status: str
    progress: int = 0
    stage: str = "loading_model"
    result_asset_ids: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class RetryGenerationRequest(BaseModel):
    confirm_unknown_status: bool = False
    confirm_cost: bool = False


class DeviceInfo(BaseModel):
    name: str
    chip: str
    mem_gb: float
    os: str
    backend: str


class ModelInfo(BaseModel):
    id: str
    role: str
    status: str
    progress_pct: int
    version: str
    size_gb: float
    license: str


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
