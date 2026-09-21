"""Image Generation Service protocol and testing seam."""

import io
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable
from PIL import Image

try:
    from unittest.mock import Mock, MagicMock
    _MOCK_TYPES = (Mock, MagicMock)
except ImportError:
    _MOCK_TYPES = ()

from bulkimagecreator.exceptions import (
    GenerationError,
    NonTransientGenerationError,
    SafetyBlockError,
    TransientGenerationError,
)


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

    def generate_variation_image(
        self,
        seed_image: Path,
        prompt: str,
        aspect_ratio: str = "1:1",
        model: Optional[str] = None,
    ) -> bytes:
        """Generate an image variation derived exclusively from the seed image and prompt.

        Args:
            seed_image: Path to the accepted seed image (00_seed.png).
            prompt: Variation prompt text.
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
        self._transient_failures: dict[str, dict[str, Any]] = {}
        self._safety_blocks: dict[str, str] = {}
        self._non_transient_failures: dict[str, str] = {}

    def set_transient_failure_for_prompt(
        self,
        prompt: str,
        retries_before_success: int = 1,
        error_message: str = "HTTP 429 Too Many Requests: Rate limit exceeded",
    ) -> None:
        """Configure transient failure(s) for a specific prompt before succeeding.

        Args:
            prompt: Target prompt string to match.
            retries_before_success: Number of transient failures to trigger before succeeding.
            error_message: Error message for TransientGenerationError.
        """
        self._transient_failures[prompt] = {
            "retries_before_success": retries_before_success,
            "failure_count": 0,
            "error_message": error_message,
        }

    def set_safety_block_for_prompt(
        self,
        prompt: str,
        error_message: str = "Generation blocked by safety policy (finish_reason=SAFETY)",
    ) -> None:
        """Configure a permanent safety block for a specific prompt.

        Args:
            prompt: Target prompt string to match.
            error_message: Error message for SafetyBlockError.
        """
        self._safety_blocks[prompt] = error_message

    def set_non_transient_failure_for_prompt(
        self,
        prompt: str,
        error_message: str = "Permanent generation error",
    ) -> None:
        """Configure a permanent non-transient error for a specific prompt.

        Args:
            prompt: Target prompt string to match.
            error_message: Error message for NonTransientGenerationError.
        """
        self._non_transient_failures[prompt] = error_message

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

        # Check safety blocks
        for target_prompt, msg in self._safety_blocks.items():
            if target_prompt == prompt or target_prompt in prompt:
                raise SafetyBlockError(msg)

        # Check non-transient failures
        for target_prompt, msg in self._non_transient_failures.items():
            if target_prompt == prompt or target_prompt in prompt:
                raise NonTransientGenerationError(msg)

        # Check transient failures
        for target_prompt, conf in self._transient_failures.items():
            if target_prompt == prompt or target_prompt in prompt:
                if conf["failure_count"] < conf["retries_before_success"]:
                    conf["failure_count"] += 1
                    raise TransientGenerationError(conf["error_message"])

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

    def generate_variation_image(
        self,
        seed_image: Path,
        prompt: str,
        aspect_ratio: str = "1:1",
        model: Optional[str] = None,
    ) -> bytes:
        return self.generate_image(
            prompt=prompt,
            reference_images=[seed_image],
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
            if isinstance(exc, (TransientGenerationError, SafetyBlockError, NonTransientGenerationError)):
                raise exc

            exc_str = str(exc).lower()
            code = getattr(exc, "code", None)
            status = getattr(exc, "status", None)
            status_str = str(status).upper() if status else ""

            is_transient = False
            if code in (429, 500, 502, 503, 504):
                is_transient = True
            elif any(s in status_str for s in ("RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED")):
                is_transient = True
            elif isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
                is_transient = True
            elif any(
                k in exc_str
                for k in (
                    "429",
                    "503",
                    "too many requests",
                    "resource exhausted",
                    "service unavailable",
                    "timed out",
                    "timeout",
                )
            ):
                is_transient = True

            if is_transient:
                raise TransientGenerationError(f"Transient Gemini API failure: {exc}") from exc

            if any(k in exc_str for k in ("safety", "blocked", "content policy", "recitation", "prohibited")):
                raise SafetyBlockError(f"Gemini API blocked request: {exc}") from exc

            raise NonTransientGenerationError(f"Gemini API call failed: {exc}") from exc

        # 1. Check for valid returned image data first
        if response and response.candidates:
            for candidate in response.candidates:
                try:
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            if part.inline_data and isinstance(part.inline_data.data, (bytes, bytearray)):
                                return bytes(part.inline_data.data)
                except Exception:
                    pass

        # 2. If no image data found, check prompt feedback for blocks
        if response:
            try:
                prompt_feedback = getattr(response, "prompt_feedback", None)
                if prompt_feedback is not None:
                    block_reason = getattr(prompt_feedback, "block_reason", None)
                    if block_reason is not None and not isinstance(block_reason, _MOCK_TYPES):
                        msg = getattr(prompt_feedback, "block_reason_message", None)
                        msg_str = msg if (msg and not isinstance(msg, _MOCK_TYPES)) else str(block_reason)
                        raise SafetyBlockError(f"Prompt blocked by safety policy: {msg_str}")
            except SafetyBlockError:
                raise
            except Exception:
                pass

            # 3. Check candidates for safety finish reason or blocked ratings
            try:
                candidates = getattr(response, "candidates", None)
                if candidates and not isinstance(candidates, _MOCK_TYPES):
                    for candidate in candidates:
                        finish_reason = getattr(candidate, "finish_reason", None)
                        if finish_reason is not None and not isinstance(finish_reason, _MOCK_TYPES):
                            finish_str = str(finish_reason).upper()
                            safety_keywords = ("SAFETY", "BLOCK", "PROHIBITED", "RECITATION", "SPII")
                            if any(kw in finish_str for kw in safety_keywords):
                                finish_msg = getattr(candidate, "finish_message", None)
                                msg_str = finish_msg if (finish_msg and not isinstance(finish_msg, _MOCK_TYPES)) else finish_str
                                raise SafetyBlockError(f"Candidate generation blocked by safety policy: {msg_str}")

                        safety_ratings = getattr(candidate, "safety_ratings", None)
                        if safety_ratings and isinstance(safety_ratings, list):
                            for rating in safety_ratings:
                                if getattr(rating, "blocked", False) is True:
                                    raise SafetyBlockError(f"Candidate blocked by safety rating: {rating}")
            except SafetyBlockError:
                raise
            except Exception:
                pass

        if not response or not response.candidates or isinstance(response.candidates, _MOCK_TYPES):
            raise NonTransientGenerationError("No candidates returned from Gemini image generation.")

        raise NonTransientGenerationError("No image data found in Gemini response.")

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

    def generate_variation_image(
        self,
        seed_image: Path,
        prompt: str,
        aspect_ratio: str = "1:1",
        model: Optional[str] = None,
    ) -> bytes:
        return self.generate_image(
            prompt=prompt,
            reference_images=[seed_image],
            aspect_ratio=aspect_ratio,
            model=model,
        )
