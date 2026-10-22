"""本地推理管线（懒加载 diffusers/transformers）。返回 PIL 图像，不落盘。"""
import io
from typing import List

from PIL import Image

from ..config import Settings
from .errors import ModelNotReadyError, OutOfMemoryError

SDXL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
BIREFNET_ID = "ZhengPeng7/BiRefNet"
DEFAULT_NEGATIVE = "模糊,低清,水印,畸形手"

_SDXL_PIPE = {}
_BIREFNET_MODEL = {}


def _to_multiple_of_8(n: int) -> int:
    return max(64, (n // 8) * 8)


def _check_precision(settings: Settings) -> None:
    if settings.precision not in ("fp16", "fp32"):
        raise ModelNotReadyError("NOT_SUPPORTED", "精度仅支持 fp16/fp32（int8 未实现）")


def _get_sdxl(settings: Settings, device: str):
    if "pipe" in _SDXL_PIPE:
        return _SDXL_PIPE["pipe"]
    import torch
    from diffusers import StableDiffusionXLPipeline

    _check_precision(settings)
    dtype = torch.float16 if settings.precision == "fp16" else torch.float32
    try:
        pipe = StableDiffusionXLPipeline.from_pretrained(
            SDXL_ID,
            torch_dtype=dtype,
            variant="fp16" if settings.precision == "fp16" else None,
            cache_dir=settings.models_dir,
            use_safetensors=True,
        )
        pipe = pipe.to(device)
        try:
            pipe.enable_attention_slicing()
        except Exception:
            pass
    except Exception as e:
        raise ModelNotReadyError("MODEL_NOT_READY", f"主模型未就绪：{e}") from e
    _SDXL_PIPE["pipe"] = pipe
    return pipe


def run_txt2img(settings: Settings, device: str, params: dict, on_progress) -> List[Image.Image]:
    import torch

    pipe = _get_sdxl(settings, device)
    width = _to_multiple_of_8(params.get("width") or 1024)
    height = _to_multiple_of_8(params.get("height") or 1024)
    steps = params.get("steps", 28)
    seed = params.get("seed", -1)
    generator = None
    if seed != -1:
        generator = torch.Generator(device=device).manual_seed(seed)

    def cb(pipe, step, timestep, kwargs):
        on_progress(int((step + 1) / steps * 70), "sampling")
        return kwargs

    try:
        images = pipe(
            prompt=params.get("prompt", ""),
            negative_prompt=params.get("negative_prompt") or DEFAULT_NEGATIVE,
            num_inference_steps=steps,
            guidance_scale=params.get("cfg", 7.0),
            width=width,
            height=height,
            generator=generator,
            num_images_per_prompt=params.get("num_images", 1),
            callback_on_step_end=cb,
        ).images
    except Exception as e:
        raise OutOfMemoryError("OUT_OF_MEMORY", f"生成失败，可降分辨率或精度重试：{e}") from e

    on_progress(85, "decoding")
    on_progress(100, "done")
    return list(images)


def _get_birefnet(settings: Settings, device: str):
    if "model" in _BIREFNET_MODEL:
        return _BIREFNET_MODEL["model"]
    import torch
    from transformers import AutoModelForImageSegmentation

    _check_precision(settings)
    dtype = torch.float16 if settings.precision == "fp16" else torch.float32
    try:
        model = AutoModelForImageSegmentation.from_pretrained(
            BIREFNET_ID, cache_dir=settings.models_dir, trust_remote_code=True, torch_dtype=dtype
        )
        model = model.to(device).eval()
    except Exception as e:
        raise ModelNotReadyError("MODEL_NOT_READY", f"抠图模型未就绪：{e}") from e
    _BIREFNET_MODEL["model"] = model
    return model


def run_matting(settings: Settings, device: str, src_bytes: bytes, on_progress) -> Image.Image:
    import torch
    from torchvision import transforms

    model = _get_birefnet(settings, device)
    src = Image.open(io.BytesIO(src_bytes)).convert("RGB")
    transform = transforms.Compose(
        [
            transforms.Resize((1024, 1024)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ]
    )
    inp = transform(src).unsqueeze(0).to(device)
    on_progress(30, "sampling")
    try:
        with torch.no_grad():
            preds = model(inp)[-1].sigmoid().cpu()
    except Exception as e:
        raise ModelNotReadyError("TASK_FAILED", f"抠图失败，可重试或手动用橡皮擦：{e}") from e

    on_progress(80, "decoding")
    mask = preds[0].squeeze()
    mask_img = transforms.ToPILImage()(mask).resize(src.size, Image.LANCZOS)
    rgba = src.convert("RGBA")
    rgba.putalpha(mask_img)
    on_progress(100, "done")
    return rgba
