"""Import-only TorchCodec surface for tensor-native ComfyUI inference."""

from __future__ import annotations

import contextlib
import importlib
import sys
import types
from collections.abc import Iterator


class _TensorInputsOnly:
    def __init__(self, *_args, **_kwargs):
        raise RuntimeError(
            "TorchCodec file decoding is disabled in ComfyUI-SAM-Audio. Pass decoded "
            "ComfyUI AUDIO, IMAGE, and MASK tensors to the node instead."
        )


class AudioDecoder(_TensorInputsOnly):
    """Placeholder for an upstream file-I/O path unused by the ComfyUI node."""


class VideoDecoder(_TensorInputsOnly):
    """Placeholder for an upstream file-I/O path unused by the ComfyUI node."""


class AudioEncoder(_TensorInputsOnly):
    """Placeholder for an optional upstream ranker disabled by this integration."""


class LazyAudioDecoder:
    """Resolve the real TorchCodec decoder only if another caller needs file I/O."""

    def __new__(cls, *args, **kwargs):
        try:
            decoder = importlib.import_module("torchcodec.decoders").AudioDecoder
        except Exception as error:
            raise RuntimeError(
                "TorchCodec audio decoding is unavailable; pass a decoded ComfyUI AUDIO value"
            ) from error
        return decoder(*args, **kwargs)


class LazyVideoDecoder:
    """Resolve the real TorchCodec decoder only if another caller needs file I/O."""

    def __new__(cls, *args, **kwargs):
        try:
            decoder = importlib.import_module("torchcodec.decoders").VideoDecoder
        except Exception as error:
            raise RuntimeError(
                "TorchCodec video decoding is unavailable; pass a decoded ComfyUI VIDEO value"
            ) from error
        return decoder(*args, **kwargs)


def _compatibility_modules() -> dict[str, types.ModuleType]:
    torchcodec = types.ModuleType("torchcodec")
    torchcodec.__path__ = []
    decoders = types.ModuleType("torchcodec.decoders")
    encoders = types.ModuleType("torchcodec.encoders")
    decoders.AudioDecoder = AudioDecoder
    decoders.VideoDecoder = VideoDecoder
    encoders.AudioEncoder = AudioEncoder
    torchcodec.decoders = decoders
    torchcodec.encoders = encoders
    return {
        "torchcodec": torchcodec,
        "torchcodec.decoders": decoders,
        "torchcodec.encoders": encoders,
    }


@contextlib.contextmanager
def torchcodec_import_compatibility() -> Iterator[None]:
    """Temporarily provide upstream's unused decoder imports without loading FFmpeg."""
    compatibility_modules = _compatibility_modules()
    missing = object()
    previous = {
        name: sys.modules.get(name, missing) for name in compatibility_modules
    }
    sys.modules.update(compatibility_modules)
    try:
        yield
    finally:
        for name, module in previous.items():
            if module is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
