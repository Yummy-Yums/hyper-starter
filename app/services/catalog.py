from functools import lru_cache


@lru_cache(maxsize=256)
def normalize_image_reference(image: str) -> str:
    """Tiny placeholder for image/type allowlists and image ID caching."""
    return image.strip().lower()
