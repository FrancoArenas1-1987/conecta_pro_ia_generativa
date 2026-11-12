from __future__ import annotations

import base64
import urllib.request
from pathlib import Path

from PIL import Image

from ..exceptions import GenerationError


class OpenAIImageProvider:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-image-1",
        size: str = "1024x1536",
        quality: str = "high",
    ) -> None:
        if not api_key or not api_key.strip():
            raise GenerationError("OPENAI_API_KEY is required for OpenAI image generation")

        try:
            from openai import OpenAI
        except Exception as exc:  # noqa: BLE001
            raise GenerationError("OpenAI package is not installed. Run: python -m pip install --upgrade openai") from exc

        self.client = OpenAI(api_key=api_key.strip(), max_retries=0)
        self.last_usage: dict = {}
        self.model = model
        self.size = size
        self.quality = quality

    def generate_image(self, prompt: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            response = self.client.images.generate(
                model=self.model,
                prompt=prompt,
                size=self.size,
                quality=self.quality,
                n=1,
            )
        except Exception as exc:  # noqa: BLE001
            raise GenerationError(f"OpenAI image generation failed: {exc}") from exc

        usage = getattr(response, "usage", None)
        self.last_usage = {
            "model": self.model, "size": self.size, "quality": self.quality,
            "request_id": getattr(response, "_request_id", None),
            "usage": usage.model_dump() if hasattr(usage, "model_dump") else (usage if isinstance(usage, dict) else {}),
        }

        if not getattr(response, "data", None):
            raise GenerationError("OpenAI image generation returned empty data")

        first = response.data[0]
        image_bytes: bytes | None = None

        b64_data = getattr(first, "b64_json", None)
        if b64_data:
            try:
                image_bytes = base64.b64decode(b64_data)
            except Exception as exc:  # noqa: BLE001
                raise GenerationError("Failed to decode OpenAI image payload") from exc

        if image_bytes is None:
            url = getattr(first, "url", None)
            if url:
                try:
                    with urllib.request.urlopen(url, timeout=60) as resp:
                        image_bytes = resp.read()
                except Exception as exc:  # noqa: BLE001
                    raise GenerationError("Failed to download generated image from OpenAI URL") from exc

        if image_bytes is None:
            raise GenerationError("OpenAI response did not include image bytes")

        # Normalize to JPG for the video renderer.
        tmp_path = output_path.parent / "_tmp_openai_image.bin"
        tmp_path.write_bytes(image_bytes)

        try:
            img = Image.open(tmp_path).convert("RGB")
            img.save(output_path, format="JPEG", quality=95)
        except Exception as exc:  # noqa: BLE001
            raise GenerationError(f"Failed to normalize generated image: {exc}") from exc
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise GenerationError("OpenAI image output file is missing or empty")

        return output_path
