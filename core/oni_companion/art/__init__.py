"""Game art served from the mod's own output (companion/art/). No art ships with this program."""
from .decorate import decorate
from .store import ART_KINDS, ArtStore, Png, art_url

__all__ = ["ART_KINDS", "ArtStore", "Png", "art_url", "decorate"]
