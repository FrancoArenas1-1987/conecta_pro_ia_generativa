from __future__ import annotations

from pathlib import Path
from typing import List, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class VoiceProfile(BaseModel):
    tone: str
    style: List[str] = Field(default_factory=list)
    avoid: List[str] = Field(default_factory=list)


class VisualIdentity(BaseModel):
    primary_color: str
    secondary_color: str
    accent_color: str
    text_color: str
    video_format: str = "vertical_9_16"


class BrandContext(BaseModel):
    company_name: str
    tagline: str
    mission: str
    positioning: dict
    brand_promises: List[str] = Field(default_factory=list)
    audience: List[str] = Field(default_factory=list)
    voice: VoiceProfile
    key_messages: List[str] = Field(default_factory=list)
    legal_safety: List[str] = Field(default_factory=list)
    service_scope: str
    call_to_action: str
    whatsapp_url: str | None = None
    website_url: str | None = None
    logo_candidates: List[str] = Field(default_factory=list)
    whatsapp_qr_path: str | None = None
    whatsapp_qr_provider_path: str | None = None
    visual_identity: VisualIdentity


class DialogueTurn(BaseModel):
    speaker: str
    line: str


class ScriptSection(BaseModel):
    index: int
    title: str
    narration: str
    onscreen_text: str


class VideoScript(BaseModel):
    topic: str
    style: Literal["promo", "dialogo", "conversion"] = "promo"
    hook: str
    sections: List[ScriptSection]
    dialogue: List[DialogueTurn] = Field(default_factory=list)
    cta: str

    @field_validator("sections")
    @classmethod
    def _validate_sections(cls, value: List[ScriptSection]) -> List[ScriptSection]:
        if len(value) < 3:
            raise ValueError("Video script must include at least 3 sections")
        return value

    @model_validator(mode="after")
    def _validate_dialogue(self) -> "VideoScript":
        if self.style == "dialogo" and len(self.dialogue) < 4:
            raise ValueError("Dialogue style requires at least 4 dialogue turns")
        return self


class StoryboardScene(BaseModel):
    index: int
    headline: str
    body: str
    duration_seconds: float = Field(gt=0)
    source_image: Path | None = None
    source_video: Path | None = None
    speaker: str | None = None
    visual_style: Literal["promo", "dialogo", "conversion"] = "promo"


class ImageCreative(BaseModel):
    headline: str
    subheadline: str
    call_to_action: str
    service_focus: str


class AssetItem(BaseModel):
    path: Path
    tags: List[str] = Field(default_factory=list)


class VideoRequest(BaseModel):
    topic: str = ""
    duration_seconds: int | None = Field(default=None, ge=5, le=180)
    enable_tts: bool = True
    enable_music: bool = True
    style: Literal["promo", "dialogo", "conversion"] = "promo"
    dialogue_seed: str | None = None
    auto_idea: bool = False
    use_openai_images: bool | None = None
    engine: Literal["studio", "comfyui"] = "studio"
    objective: Literal["captar_clientes", "captar_proveedores", "branding"] | None = None
    enable_variant_exploration: bool = True
    max_variant_candidates: int = Field(default=12, ge=1, le=24)


class ImageRequest(BaseModel):
    context: str
    service: str
    width: int = Field(default=1080, ge=720, le=2048)
    height: int = Field(default=1350, ge=720, le=2048)


class CampaignRequest(BaseModel):
    name: str
    base_topic: str
    objective: Literal["captar_clientes", "captar_proveedores", "branding"] = "captar_clientes"
    tone: str = "directo"
    strategy: Literal["conversion", "promo"] = "conversion"
    variants_per_segment: int = Field(default=2, ge=1, le=5)
    segments: list[dict] = Field(default_factory=list)


class GenerationOutput(BaseModel):
    run_id: str
    run_dir: Path
    type: str
    main_file: Path
    metadata_file: Path
