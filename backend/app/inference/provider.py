"""模型接入抽象层：可切换 provider。返回 PIL 图像，不落盘。

- DashScopeProvider：阿里云百炼（通义万相/qwen-image）真实 API，同步接口。
- RemBgProvider：本地轻量抠图（U2Net，约 170MB 一次性下载）。
- LocalProvider：本地 diffusers 推理（保留接口，未来本地部署用）。
"""
import io
from typing import List

import requests
from PIL import Image

from ..config import Settings
from .errors import ProviderError


class BaseProvider:
    name = "base"

    def txt2img(self, params: dict, on_progress) -> List[Image.Image]:
        raise NotImplementedError

    def matting(self, src_bytes: bytes, on_progress) -> Image.Image:
        raise NotImplementedError


class DashScopeProvider(BaseProvider):
    """百炼文生图（qwen-image 系列，messages 格式，同步返回图片 URL）。"""

    name = "dashscope"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.key = settings.dashscope_api_key
        self.base = settings.dashscope_base_url.rstrip("/") if settings.dashscope_base_url else ""
        self.model = settings.dashscope_txt2img_model
        if not self.key:
            raise ProviderError("UNAUTHORIZED", "未配置 DASHSCOPE_API_KEY")
        if not self.base:
            raise ProviderError("INVALID_PARAMS", "未配置 DASHSCOPE_BASE_URL（需包含 WorkspaceId）")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    def _download(self, url: str) -> Image.Image:
        r = requests.get(url, timeout=180)
        if r.status_code >= 400:
            raise ProviderError("TASK_FAILED", f"下载生成结果失败 {r.status_code}")
        img = Image.open(io.BytesIO(r.content))
        img.load()
        return img

    @staticmethod
    def _clamp(n: int) -> int:
        return max(512, min(2048, n))

    def txt2img(self, params: dict, on_progress) -> List[Image.Image]:
        on_progress(5, "loading_model")
        prompt = params.get("prompt", "")
        w = self._clamp(params.get("width") or 1024)
        h = self._clamp(params.get("height") or 1024)
        # 宽高比超范围时回退到方图
        if not (1 / 8 <= w / h <= 8):
            w = h = 1024
        n = max(1, min(6, params.get("num_images", 1)))
        body = {
            "model": self.model,
            "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
            "parameters": {"size": f"{w}*{h}", "n": n, "prompt_extend": True},
        }
        try:
            r = requests.post(
                f"{self.base}/services/aigc/multimodal-generation/generation",
                headers=self._headers(),
                json=body,
                timeout=180,
            )
        except requests.Timeout as e:
            raise ProviderError("TASK_FAILED", "请求超时，云端状态不明，请到百炼控制台确认是否已生成/扣费后再试") from e
        except requests.RequestException as e:
            raise ProviderError("TASK_FAILED", f"请求失败：{e}") from e

        if r.status_code == 401:
            raise ProviderError("UNAUTHORIZED", "API Key 无效或无权限")
        if r.status_code >= 400:
            raise ProviderError("TASK_FAILED", f"API 错误 {r.status_code}：{r.text[:200]}")

        data = r.json()
        choices = ((data.get("output") or {}).get("choices")) or []
        urls: List[str] = []
        for c in choices:
            for item in ((c.get("message") or {}).get("content")) or []:
                if item.get("image"):
                    urls.append(item["image"])
        if not urls:
            raise ProviderError("TASK_FAILED", "未获取到图片 URL，返回内容与预期不符")
        on_progress(85, "decoding")
        images = [self._download(u) for u in urls]
        on_progress(100, "done")
        return images

    def matting(self, src_bytes: bytes, on_progress) -> Image.Image:
        raise ProviderError("NOT_SUPPORTED", "百炼不提供通用商品抠图，请使用本地 rembg 抠图")


class RemBgProvider(BaseProvider):
    """本地轻量抠图：rembg + U2Net（约 170MB 一次性下载，离线可用）。"""

    name = "rembg"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _session(self):
        if not hasattr(self, "_sess"):
            import rembg

            self._sess = rembg.new_session("u2net")
        return self._sess

    def matting(self, src_bytes: bytes, on_progress) -> Image.Image:
        on_progress(10, "loading_model")
        import rembg

        out = rembg.remove(src_bytes, session=self._session())
        img = Image.open(io.BytesIO(out)).convert("RGBA")
        on_progress(100, "done")
        return img

    def txt2img(self, params: dict, on_progress) -> List[Image.Image]:
        raise ProviderError("NOT_SUPPORTED", "rembg 仅用于抠图")


class LocalProvider(BaseProvider):
    """本地 diffusers 推理（保留接口，暂不作为默认接入）。"""

    name = "local"

    def __init__(self, settings: Settings, device: str) -> None:
        self.settings = settings
        self.device = device

    def txt2img(self, params: dict, on_progress) -> List[Image.Image]:
        from .pipelines import run_txt2img

        return run_txt2img(self.settings, self.device, params, on_progress)

    def matting(self, src_bytes: bytes, on_progress) -> Image.Image:
        from .pipelines import run_matting

        return run_matting(self.settings, self.device, src_bytes, on_progress)
