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
    def generate_candidate_image(
        self,
        source_images: list[Path],
        prompt: str,
        aspect_ratio: str = "1:1",
        model: Optional[str] = None,
    ) -> bytes:
        """Generate a candidate seed image during the Seed Phase from source images and prompt.

        Args:
            source_images: Paths to 1 to 4 source images.
            prompt: Seed prompt text.
            aspect_ratio: Desired aspect ratio ("1:1", "3:4", "4:3", "9:16", "16:9").
            model: Model name override or None for default.

        Returns:
            Raw image bytes.
        """
        ...


class MockImageGenerationService:
    """Mock implementation of ImageGenerationService for testing and dry runs."""

    def __init__(self, output_bytes: Optional[bytes | list[bytes]] = None) -> None:
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
        if isinstance(self._output_bytes, list) and self._output_bytes:
            return self._output_bytes.pop(0)
        elif isinstance(self._output_bytes, bytes):
            return self._output_bytes

        # Generate a lightweight deterministic PNG image with distinct color per call
        call_count = len(self.call_history)
        r = (60 + call_count * 45) % 256
        g = (90 + call_count * 35) % 256
        b = (130 + call_count * 25) % 256
        img = Image.new("RGB", (128, 128), color=(r, g, b))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def generate_candidate_image(
        self,
        source_images: list[Path],
        prompt: str,
        aspect_ratio: str = "1:1",
        model: Optional[str] = None,
    ) -> bytes:
        return self.generate_image(
            prompt=prompt,
            reference_images=source_images,
            aspect_ratio=aspect_ratio,
            model=model,
        )


class GeminiImageGenerationService:
    """Production implementation of ImageGenerationService using Google GenAI SDK."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "gemini-2.5-flash-image",
        client: Optional[Any] = None,
    ) -> None:
        import os

        self.default_model = default_model
        if client is not None:
            self._client = client
        else:
            resolved_key = api_key or os.environ.get("GEMINI_API_KEY")
            from google import genai

            self._client = genai.Client(api_key=resolved_key)

    def generate_image(
        self,
        prompt: str,
        reference_images: list[Path],
        aspect_ratio: str = "1:1",
        model: Optional[str] = None,
    ) -> bytes:
        from google.genai import types
        from bulkimagecreator.exceptions import GenerationError

        model_name = model or self.default_model

        contents: list[Any] = []
        for img_path in reference_images:
            resolved_path = Path(img_path).resolve()
            with Image.open(resolved_path) as img:
                contents.append(img.copy())
        contents.append(prompt)

        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
        )

        try:
            response = self._client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            raise GenerationError(f"Gemini API call failed: {exc}") from exc

        if not response or not response.candidates:
            raise GenerationError("No candidates returned from Gemini image generation.")

        for candidate in response.candidates:
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if part.inline_data and part.inline_data.data:
                        return part.inline_data.data

        raise GenerationError("No image data found in Gemini response.")

    def generate_candidate_image(
        self,
        source_images: list[Path],
        prompt: str,
        aspect_ratio: str = "1:1",
        model: Optional[str] = None,
    ) -> bytes:
        return self.generate_image(
            prompt=prompt,
            reference_images=source_images,
            aspect_ratio=aspect_ratio,
            model=model,
        )
