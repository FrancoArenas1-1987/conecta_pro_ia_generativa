from __future__ import annotations

from pathlib import Path

from .models import AssetItem

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


class AssetLibrary:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.image_items, self.video_items, self.audio_items = self._index_assets(root)
        self.items = self.image_items + self.video_items + self.audio_items

    @staticmethod
    def _to_tags(path: Path) -> list[str]:
        tags: list[str] = []
        for part in path.parts:
            norm = "".join(ch.lower() if ch.isalnum() else " " for ch in part)
            tags.extend([token for token in norm.split() if token])
        return sorted(set(tags))

    def _index_assets(self, root: Path) -> tuple[list[AssetItem], list[AssetItem], list[AssetItem]]:
        images: list[AssetItem] = []
        videos: list[AssetItem] = []
        audios: list[AssetItem] = []

        for file in root.rglob("*"):
            if not file.is_file():
                continue

            ext = file.suffix.lower()
            item = AssetItem(path=file, tags=self._to_tags(file))

            if ext in _IMAGE_EXTENSIONS:
                images.append(item)
                continue

            if ext in _VIDEO_EXTENSIONS:
                # Avoid using reference InVideo exports as raw footage in auto mode.
                low_name = file.name.lower()
                if "invideo-ai" in low_name:
                    continue
                videos.append(item)
                continue

            if ext in _AUDIO_EXTENSIONS:
                audios.append(item)

        return images, videos, audios

    @staticmethod
    def _expand_query_tags(query_tags: set[str]) -> set[str]:
        synonyms: dict[str, set[str]] = {
            "gasfiter": {"gasfiter", "gasfiteria", "plomeria", "plomero", "calefon", "fuga", "llave"},
            "electricista": {"electricista", "electricidad", "enchufe", "tablero", "cable", "luz"},
            "abogado": {"abogado", "legal", "juridico", "demanda", "contrato"},
            "kinesiologia": {"kinesiologia", "kine", "rehabilitacion", "dolor", "terapia"},
            "whatsapp": {"whatsapp", "mensaje", "chat", "celular", "movil"},
            "servicios": {"servicio", "servicios", "profesional", "profesionales", "tecnico", "especialista"},
            "dialogo": {"dialogo", "conversacion", "hablando", "personas", "pareja", "cliente", "asesor"},
            "promocion": {"promo", "promocion", "publicidad", "oferta", "reel", "anuncio"},
            "comofunciona": {"comofunciona", "paso", "pasos", "proceso", "flujo", "como"},
            "sincosto": {"gratis", "sin", "costo", "sincosto"},
        }

        expanded = set(query_tags)
        for key, terms in synonyms.items():
            if key in query_tags or query_tags.intersection(terms):
                expanded.update(terms)
        return expanded

    def _score_item(self, item: AssetItem, query_tags: set[str]) -> int:
        item_tags = set(item.tags)
        overlap = len(query_tags.intersection(item_tags))
        score = overlap * 12

        service_tags = {
            "gasfiter",
            "gasfiteria",
            "electricista",
            "electricidad",
            "abogado",
            "kinesiologia",
            "kine",
            "maestro",
            "servicios",
            "ofrecetusservicios",
            "comofunciona",
            "sincosto",
        }

        if query_tags.intersection({"servicios", "profesional", "profesionales", "promo", "publicidad", "reel"}):
            score += 10 * len(service_tags.intersection(item_tags))

        if query_tags.intersection({"dialogo", "conversacion", "personas", "cliente", "asesor"}):
            if {"cliente", "personas", "servicios", "publicacion", "comofunciona"}.intersection(item_tags):
                score += 10

        # Penalize generic brand-cover assets for scene-level storytelling.
        generic_brand_assets = {"perfil", "portada", "facebook", "u", "concepcion"}
        generic_hits = len(generic_brand_assets.intersection(item_tags))
        score -= generic_hits * 6

        return score

    def _rank_items(self, text: str, items: list[AssetItem], avoid: set[Path] | None = None) -> list[tuple[int, int, AssetItem]]:
        if not items:
            return []

        query_tags = self._expand_query_tags(set(self._to_tags(Path(text))))
        avoid = avoid or set()

        ranked: list[tuple[int, int, AssetItem]] = []
        for idx, item in enumerate(items):
            if item.path in avoid:
                continue
            ranked.append((self._score_item(item, query_tags), idx, item))

        if not ranked:
            ranked = [(self._score_item(item, query_tags), idx, item) for idx, item in enumerate(items)]

        ranked.sort(key=lambda x: (x[0], -x[1]), reverse=True)
        return ranked

    def best_match(self, text: str, avoid: set[Path] | None = None) -> AssetItem:
        # Backward-compatible behavior: images first, then videos if no images are available.
        if self.image_items:
            return self.best_match_image(text, avoid=avoid)
        if self.video_items:
            return self.best_match_video(text, avoid=avoid)
        raise ValueError("No assets found")

    def best_match_image(self, text: str, avoid: set[Path] | None = None) -> AssetItem:
        if not self.image_items:
            raise ValueError("No image assets found")

        ranked = self._rank_items(text, self.image_items, avoid=avoid)
        if not ranked:
            raise ValueError("No image assets available after filtering")

        if ranked[0][0] == 0:
            pick = abs(hash(text)) % len(ranked)
            return ranked[pick][2]
        return ranked[0][2]

    def best_match_video(self, text: str, avoid: set[Path] | None = None) -> AssetItem:
        if not self.video_items:
            raise ValueError("No video assets found")

        ranked = self._rank_items(text, self.video_items, avoid=avoid)
        if not ranked:
            raise ValueError("No video assets available after filtering")

        if ranked[0][0] == 0:
            pick = abs(hash(text)) % len(ranked)
            return ranked[pick][2]
        return ranked[0][2]

    def top_images(self, text: str, limit: int = 5, avoid: set[Path] | None = None) -> list[AssetItem]:
        ranked = self._rank_items(text, self.image_items, avoid=avoid)
        return [item for _, _, item in ranked[: max(1, limit)]]

    def top_videos(self, text: str, limit: int = 5, avoid: set[Path] | None = None) -> list[AssetItem]:
        ranked = self._rank_items(text, self.video_items, avoid=avoid)
        return [item for _, _, item in ranked[: max(1, limit)]]
