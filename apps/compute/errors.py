"""Stable transport/domain diagnostic codes without URLs or credentials."""


class ComputeError(RuntimeError):
    def __init__(self, code: str, status: int = 0) -> None:
        self.code = code
        self.status = status
        super().__init__(code)
