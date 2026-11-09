"""Modul audio: nada per warna + ucapan TTS Bahasa Indonesia."""
from .speaker import SoundEngine
from .tone_factory import generate_all, list_sounds

__all__ = ["SoundEngine", "generate_all", "list_sounds"]
