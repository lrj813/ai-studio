"""推理统一错误：带错误码，供任务层映射到统一响应结构。"""


class InferenceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class ModelNotReadyError(InferenceError):
    pass


class OutOfMemoryError(InferenceError):
    pass


class ProviderError(InferenceError):
    pass
