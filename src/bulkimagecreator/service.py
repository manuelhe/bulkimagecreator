"""Image Generation Service protocol and testing seam."""

import io
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable
from PIL import Image


@runtime_checkable
class ImageGenerationService(Protocol):
    """Protocol defining the multimodal image generation boundary.

    Acts as the architectural seam for API calls to Gemini multimodal image generation,
    enabling complete test isolation without external network calls.
    """

    def generate_image(
        self,
        prompt: str,
        reference_images: list[Path],
        aspect_ratio: str = "1:1",
        model: Optional[str] = None,
    ) -> bytes:
        """Generate an image from text prompt and reference images, returning raw image bytes.

        Args:
            prompt: Text prompt describing desired output.
            reference_images: Paths to reference images (1 to 4 source images or 1 seed image).
            aspect_ratio: Desired aspect ratio ("1:1", "3:4", "4:3", "9:16", "16:9").
            model: Model name override or None for default.

        Returns:
            Raw image bytes (PNG or WebP).
        """
        ...


class MockImageGenerationService:
    """Mock implementation of ImageGenerationService for testing and dry runs."""

    def __init__(self, output_bytes: Optional[bytes] = None) -> None:
        self._output_bytes = output_bytes
        self.call_history: list[dict[str, Any]] = []

    def generate_image(
        self,
        prompt: str,
        reference_images: list[Path],
        aspect_ratio: str = "1:1",
        model: Optional[str] = None,
    ) -> bytes:
        self.call_history.append(
            {
                "prompt": prompt,
                "reference_images": list(reference_images),
                "aspect_ratio": aspect_ratio,
                "model": model,
            }
        )
        if self._output_bytes is not None:
            return self._output_bytes

        # Generate a lightweight deterministic PNG image
        img = Image.new("RGB", (128, 128), color=(73, 109, 137))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
