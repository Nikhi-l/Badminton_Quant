import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"


def test_landing_preserves_the_existing_product_routes():
    landing_html = (WEB / "index.html").read_text()
    product_html = (WEB / "create.html").read_text()

    assert 'data-deployment="baddy-landing-v1"' in landing_html
    assert "/create.html${window.location.hash}" in landing_html
    assert "studio(?:\\/|$)" in landing_html

    # The production uploader, queue, gallery, and Studio must remain intact.
    assert 'id="file"' in product_html
    assert 'id="jobPanel"' in product_html
    assert 'id="gallery"' in product_html
    assert 'id="studio"' in product_html
    assert '<script src="/app.js?v=41"></script>' in product_html
    assert '<script src="/replay3d.js?v=32"></script>' in product_html


def test_landing_bundle_targets_the_product_instead_of_looping_to_root():
    manifest = json.loads((WEB / "landing" / "asset-manifest.json").read_text())
    main_js_path = WEB / manifest["files"]["main.js"].lstrip("/")
    main_css_path = WEB / manifest["files"]["main.css"].lstrip("/")

    assert main_js_path.is_file()
    assert main_css_path.is_file()

    bundle = main_js_path.read_text()
    assert "/create.html#create" in bundle
    assert "/create.html#gallery" in bundle
    assert "https://baddyai.com/#create" not in bundle
    assert "baddy-phone-hero" not in bundle


def test_original_editor_and_rally_assets_are_deployed():
    required_assets = {
        "baddy-studio-editor-original.jpg",
        "baddy-rally-tracked-original.jpg",
        "baddy-rally-upload-original.jpg",
    }

    for asset_name in required_assets:
        asset = WEB / "assets" / asset_name
        assert asset.is_file()
        assert asset.stat().st_size > 20_000
        assert asset.read_bytes()[:3] == b"\xff\xd8\xff"
