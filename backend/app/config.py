"""配置读取：.env → 环境变量。不含任何密钥回显。"""
import os
from dataclasses import dataclass
from pathlib import Path


def _load_env() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: str = "./data"
    models_dir: str = "./models"
    inference_backend: str = "auto"
    precision: str = "fp16"
    max_concurrent: int = 1
    mem_budget_gb: float = 8.0
    demo_activation_code: str = ""
    # 生成接入方式：dashscope（阿里云百炼，当前演示默认）| local（本地推理，保留接口）
    inference_provider: str = "dashscope"
    dashscope_api_key: str = ""
    dashscope_base_url: str = ""  # 如 https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1
    dashscope_txt2img_model: str = "qwen-image-3.0-pro"
    # 抠图接入：rembg（本地轻量 U2Net，约 170MB）
    matting_provider: str = "rembg"


def get_settings() -> Settings:
    _load_env()
    return Settings(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        data_dir=os.environ.get("DATA_DIR", "./data"),
        models_dir=os.environ.get("MODELS_DIR", "./models"),
        inference_backend=os.environ.get("INFERENCE_BACKEND", "auto"),
        precision=os.environ.get("PRECISION", "fp16"),
        max_concurrent=int(os.environ.get("MAX_CONCURRENT", "1")),
        mem_budget_gb=float(os.environ.get("MEM_BUDGET_GB", "8")),
        demo_activation_code=os.environ.get("DEMO_ACTIVATION_CODE", ""),
        inference_provider=os.environ.get("INFERENCE_PROVIDER", "dashscope"),
        dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        dashscope_base_url=os.environ.get("DASHSCOPE_BASE_URL", ""),
        dashscope_txt2img_model=os.environ.get("DASHSCOPE_TXT2IMG_MODEL", "qwen-image-3.0-pro"),
        matting_provider=os.environ.get("MATTING_PROVIDER", "rembg"),
    )
