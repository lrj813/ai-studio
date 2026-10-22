import os
import platform
import subprocess
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends

from ..config import Settings
from ..deps import get_settings, get_store
from ..schemas import DeviceInfo, ModelInfo
from ..store import Store

router = APIRouter(prefix="/api", tags=["system"])


def _chip() -> str:
    try:
        out = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        if out:
            return out
    except Exception:
        pass
    return platform.machine()


def _mem_gb() -> float:
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        return round(page * pages / 1024 ** 3, 1)
    except Exception:
        return 0.0


@router.get("/device", response_model=DeviceInfo)
def get_device(store: Store = Depends(get_store), settings: Settings = Depends(get_settings)):
    from ..inference.engine import InferenceEngine

    engine = InferenceEngine(settings, store)
    return DeviceInfo(
        name=platform.node(),
        chip=_chip(),
        mem_gb=_mem_gb(),
        os=platform.system(),
        backend=engine.backend,
    )


@router.get("/models", response_model=List[ModelInfo])
def list_models(settings: Settings = Depends(get_settings)):
    if settings.inference_provider == "dashscope":
        gen_ready = "ready" if (settings.dashscope_api_key and settings.dashscope_base_url) else "missing"
        u2net = Path.home() / ".rembg" / "models" / "u2net" / "u2net.onnx"
        mat_ready = "ready" if u2net.exists() else "missing"
        return [
            ModelInfo(id=settings.dashscope_txt2img_model, role="main", status=gen_ready, progress_pct=100 if gen_ready == "ready" else 0, version="百炼 API", size_gb=0.0, license="商用（按阿里云协议）"),
            ModelInfo(id="rembg-u2net", role="matting", status=mat_ready, progress_pct=100 if mat_ready == "ready" else 0, version="U2Net（本地）", size_gb=0.17, license="Apache-2.0"),
        ]

    models_dir = Path(settings.models_dir)

    def status(repo_id: str) -> str:
        marker = models_dir / ("models--" + repo_id.replace("/", "--"))
        if not marker.exists():
            return "missing"
        weights = list(marker.rglob("*.safetensors")) + list(marker.rglob("*.bin"))
        return "ready" if weights else "partial"

    return [
        ModelInfo(
            id="sdxl-1.0",
            role="main",
            status=status("stabilityai/stable-diffusion-xl-base-1.0"),
            progress_pct=100 if status("stabilityai/stable-diffusion-xl-base-1.0") == "ready" else 0,
            version="1.0",
            size_gb=7.0,
            license="openrail++",
        ),
        ModelInfo(
            id="birefnet",
            role="matting",
            status=status("ZhengPeng7/BiRefNet"),
            progress_pct=100 if status("ZhengPeng7/BiRefNet") == "ready" else 0,
            version="1.4",
            size_gb=1.0,
            license="MIT",
        ),
    ]


@router.get("/health")
def health(store: Store = Depends(get_store), settings: Settings = Depends(get_settings)):
    from ..inference.engine import InferenceEngine

    engine = InferenceEngine(settings, store)
    return {"ok": True, "provider": settings.inference_provider, "backend": engine.backend}
