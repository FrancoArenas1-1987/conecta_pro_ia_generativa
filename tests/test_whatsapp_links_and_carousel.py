from pathlib import Path

from PIL import Image

from conecta_video_ai.whatsapp_links import extract_whatsapp_phone, normalize_whatsapp_click_url
import scripts.run_instagram_carousel_once as carousel
from scripts.run_instagram_carousel_once import choose_theme, load_assets


def test_normalize_whatsapp_click_url_converts_short_links_to_mobile_send_url() -> None:
    url = normalize_whatsapp_click_url("https://wa.me/56983434503")

    assert url == "https://api.whatsapp.com/send?phone=56983434503"
    assert extract_whatsapp_phone(url) == "+56983434503"


def test_carousel_loads_nested_assets_and_prefers_newest_image(tmp_path: Path) -> None:
    assets_root = tmp_path / "imagenes_ig"
    flat_old = assets_root / "gasfiteria_01.png"
    nested_new = assets_root / "gasfiteria" / "images" / "openai_generated.jpg"
    nested_new.parent.mkdir(parents=True, exist_ok=True)
    assets_root.mkdir(parents=True, exist_ok=True)

    Image.new("RGB", (1080, 1350), color=(10, 20, 30)).save(flat_old)
    Image.new("RGB", (1080, 1350), color=(40, 50, 60)).save(nested_new)
    flat_old.touch()
    nested_new.touch()

    grouped = load_assets(assets_root)

    assert "gasfiteria" in grouped
    assert grouped["gasfiteria"][0] == nested_new


def test_carousel_builds_dynamic_recent_services_theme_for_new_categories(tmp_path: Path) -> None:
    assets_root = tmp_path / "imagenes_ig"
    for category in ["peluqueria_canina", "arquitectura", "abogado"]:
        image_path = assets_root / category / "images" / "openai_generated.jpg"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1080, 1350), color=(80, 120, 160)).save(image_path)
        image_path.touch()

    grouped = load_assets(assets_root)
    theme = choose_theme(grouped)

    assert theme["id"] == "servicios_recientes"
    assert "peluqueria_canina" in theme["categories"]


def test_carousel_font_uses_linux_dejavu_before_bitmap_fallback(monkeypatch) -> None:
    class FakeFont:
        pass

    linux_font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    monkeypatch.setattr(
        carousel,
        "_font_paths",
        lambda *, bold: [Path(r"C:\Windows\Fonts\arialbd.ttf"), linux_font],
    )
    monkeypatch.setattr(Path, "exists", lambda self: self == linux_font)

    def fake_truetype(path: str, *, size: int):
        assert path == str(linux_font)
        assert size == 76
        return FakeFont()

    monkeypatch.setattr(carousel.ImageFont, "truetype", fake_truetype)
    monkeypatch.setattr(
        carousel.ImageFont,
        "load_default",
        lambda: (_ for _ in ()).throw(AssertionError("bitmap fallback should not be used")),
    )

    assert isinstance(carousel.font(76, bold=True), FakeFont)
