"""推理引擎门面：按配置选择生成 provider 与抠图 provider，把模型输出落成素材资产。"""
import io
from pathlib import Path
from typing import Any, Callable, Dict, List

from PIL import Image

from ..config import Settings
from ..store import Store, new_id, sha256_bytes
from .errors import ModelNotReadyError, ProviderError
from .provider import BaseProvider, DashScopeProvider, LocalProvider, RemBgProvider

ProgressFn = Callable[[int, str], None]


class InferenceEngine:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store
        self.backend = self._detect_backend()
        self._gen_provider: BaseProvider | None = None
        self._mat_provider: BaseProvider | None = None

    def _detect_backend(self) -> str:
        if self.settings.inference_backend != "auto":
            return self.settings.inference_backend
        try:
            import torch  # noqa: F401

            if torch.cuda.is_available():
                return "cuda"
            if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                return "mps"
            return "cpu"
        except Exception:
            return "cpu"

    def _device(self) -> str:
        return {"mps": "mps", "cuda": "cuda"}.get(self.backend, "cpu")

    @property
    def gen_provider(self) -> BaseProvider:
        if self._gen_provider is None:
            if self.settings.inference_provider == "dashscope":
                self._gen_provider = DashScopeProvider(self.settings)
            elif self.settings.inference_provider == "local":
                self._gen_provider = LocalProvider(self.settings, self._device())
            else:
                raise ProviderError("NOT_SUPPORTED", f"未知生成接入方式：{self.settings.inference_provider}")
        return self._gen_provider

    @property
    def mat_provider(self) -> BaseProvider:
        if self._mat_provider is None:
            if self.settings.matting_provider == "rembg":
                self._mat_provider = RemBgProvider(self.settings)
            else:
                raise ProviderError("NOT_SUPPORTED", f"未知抠图接入方式：{self.settings.matting_provider}")
        return self._mat_provider

    def run(
        self,
        mode: str,
        params: Dict[str, Any],
        project_id: str,
        on_progress: ProgressFn,
    ) -> Dict[str, Any]:
        if mode == "txt2img":
            images = self.gen_provider.txt2img(params, on_progress)
            return self._save_images(images, project_id, "generated", "生成")
        if mode == "matting":
            ref_id = params.get("ref_asset_id")
            asset = self.store.get_asset(ref_id) if ref_id else None
            if asset is None:
                raise ModelNotReadyError("ASSET_NOT_FOUND", "参考素材不存在")
            src_bytes = Path(asset["path"]).read_bytes()
            img = self.mat_provider.matting(src_bytes, on_progress)
            name = f"{asset['filename'].rsplit('.', 1)[0]}-抠图"
            return self._save_images([img], project_id, "matting", name)
        raise ProviderError("NOT_SUPPORTED", f"不支持的生成模式：{mode}")

    def _save_images(self, images: List[Image.Image], project_id: str, kind: str, name_prefix: str) -> Dict[str, Any]:
        asset_ids: List[str] = []
        for i, img in enumerate(images):
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            data = buf.getvalue()
            aid = new_id("a")
            path = self.store.write_asset_file(project_id, aid, data, ".png")
            self.store.add_asset(
                project_id=project_id,
                kind=kind,
                filename=f"{name_prefix}-{i + 1}.png" if len(images) > 1 else f"{name_prefix}.png",
                path=path,
                width=img.width,
                height=img.height,
                sha256=sha256_bytes(data),
                asset_id=aid,
            )
            asset_ids.append(aid)
        return {"asset_ids": asset_ids}
