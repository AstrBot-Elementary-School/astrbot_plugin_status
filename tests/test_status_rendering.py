from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from jinja2 import Template
from PIL import Image

from tests.support import (
    create_core_package,
    install_astrbot_stubs,
    install_psutil_stub,
    load_core_module,
)

ROOT = Path(__file__).resolve().parents[1]
T2I_ENDPOINT = "http://localhost:8999/text2img/generate"
PACKAGE_NAME = "status_core_rendering_tests"

install_astrbot_stubs(include_event=True)
install_psutil_stub()
create_core_package(PACKAGE_NAME)

load_core_module(PACKAGE_NAME, "constants")
load_core_module(PACKAGE_NAME, "logger")
load_core_module(PACKAGE_NAME, "models")
load_core_module(PACKAGE_NAME, "utils")
load_core_module(PACKAGE_NAME, "data_source")
load_core_module(PACKAGE_NAME, "config_manager")
load_core_module(PACKAGE_NAME, "bot_identity_resolver")
html_render_module = load_core_module(PACKAGE_NAME, "html_render")

HtmlRender = html_render_module.HtmlRender


class _FakeTrafficRecorder:
    async def sample(self) -> SimpleNamespace:
        return SimpleNamespace(
            card_text="Jul  ↑ 1.0 MB | ↓ 2.0 MB",
            summary_text="合计 3.0 MB，上传 1.0 MB，下载 2.0 MB",
        )


def _metric(
    icon_class: str, label: str, value: str, offset: float
) -> dict[str, object]:
    return {
        "icon_class": icon_class,
        "label": label,
        "value": value,
        "offset": offset,
    }


def _render_payload() -> tuple[str, dict[str, object]]:
    html = (ROOT / "templates/main.html").read_text(encoding="utf-8-sig")
    css = (ROOT / "templates/res/css/style.css").read_text(encoding="utf-8-sig")
    css = css.replace("${topBannerImage}", "")
    css = css.replace("${characterImage}", "")

    payload: dict[str, object] = {
        "css_style": f"<style>{css}</style>",
        "bot_name": "AstrBot",
        "metrics": [
            _metric("icon-cpu", "CPU", "12.3% - 3.20GHz [8 Core]", 297.55),
            _metric("icon-ram", "RAM", "4.25 / 16.00 GB", 249.11),
            _metric("icon-swap", "SWAP", "0.00 / 2.00 GB", 339.29),
            _metric("icon-disk", "DISK", "120.00 / 512.00 GB", 259.79),
            _metric("icon-load", "LOAD", "22.0% / 100%", 264.65),
        ],
        "cpu_name": "Apple M1 Pro",
        "os_name": "Darwin 25.0.0",
        "project_version": "AstrBot v4.0.0",
        "plugin_count": "12",
        "upload_speed": "1.2",
        "download_speed": "3.4",
        "monthly_traffic": "Jul  ↑ 1.0 GB | ↓ 2.0 GB",
        "dashboard_name": "AstrBot",
        "uptime": "00:12:34",
    }
    return html, payload


def test_background_paws_stay_inside_card() -> None:
    html = (ROOT / "templates/main.html").read_text(encoding="utf-8-sig")
    card_start = html.index('<div class="card">')
    card_end = html.index("</div>\n\n</body>")

    for class_name in (
        "bg-tiny-paw",
        "bg-small-paw",
        "bg-medium-paw",
        "bg-big-paw",
    ):
        paw_index = html.index(class_name)
        assert card_start < paw_index < card_end


def test_template_viewport_matches_card_width() -> None:
    html = (ROOT / "templates/main.html").read_text(encoding="utf-8-sig")

    assert 'content="width=500' in html
    assert "height=1000" not in html


def test_rendered_template_contains_paw_decorations() -> None:
    html, payload = _render_payload()
    rendered = Template(html).render(
        **{
            key: [
                SimpleNamespace(**item) if isinstance(item, dict) else item
                for item in value
            ]
            if key == "metrics"
            else value
            for key, value in payload.items()
        }
    )

    assert 'class="card"' in rendered
    assert rendered.count("bg-") >= 4
    assert "Traffic" in rendered
    assert "Jul  ↑ 1.0 GB | ↓ 2.0 GB" in rendered


@pytest.mark.asyncio
async def test_render_payload_truncates_long_card_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResolver:
        async def resolve(self, _event: object) -> str:
            return "SuperLongAstrBotDisplayName"

    class FakeDataSource:
        def get_metrics(self) -> list[object]:
            return []

        async def get_cpu_name(self) -> str:
            return "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz"

        def get_os_name(self) -> str:
            return "Linux 6.12.74+deb13+1-cloud-amd64-extended"

        def get_project_version(self, _event: object) -> str:
            return "AstrBot"

        async def get_plugin_counts(self) -> int:
            return 0

        def get_net_speed_kbs(self) -> tuple[float, float]:
            return 0.0, 0.0

        def get_uptime_text(self) -> str:
            return "00:00:00"

    async def fake_html_render(*_args: object, **_kwargs: object) -> str:
        return "image-url"

    monkeypatch.setattr(html_render_module, "get_random_file_data_uri", lambda **_: "")
    monkeypatch.setattr(html_render_module, "inline_fonts_in_css", lambda css, _: css)

    renderer = HtmlRender(
        context=SimpleNamespace(),
        config_manager=SimpleNamespace(
            banner_paths=[],
            traffic_monitor=SimpleNamespace(enabled=True),
        ),
        base_dir=ROOT,
        plugin_data_dir=ROOT,
        html_render=fake_html_render,
        data_source=FakeDataSource(),
        bot_identity_resolver=FakeResolver(),
        traffic_recorder=_FakeTrafficRecorder(),
    )

    _, payload = await renderer.build_render_data(SimpleNamespace())

    assert payload.bot_name == "SuperL...ayName"
    assert payload.cpu_name == "Intel(R) Xeon(R) ...CL CPU @ 2.50GHz"
    assert payload.os_name == "Linux 6.12.74+deb...d-amd64-extended"
    assert payload.monthly_traffic == "Jul  ↑ 1.0 MB | ↓ 2.0 MB"


@pytest.mark.asyncio
async def test_status_text_includes_monthly_traffic() -> None:
    class FakeResolver:
        async def resolve(self, _event: object) -> str:
            return "AstrBot"

    class FakeDataSource:
        def get_metrics(self) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(label="CPU", value="1.0%"),
                SimpleNamespace(label="RAM", value="1 / 2 GB"),
                SimpleNamespace(label="SWAP", value="0 / 1 GB"),
                SimpleNamespace(label="DISK", value="1 / 10 GB"),
                SimpleNamespace(label="LOAD", value="1.0% / 100%"),
            ]

        async def get_cpu_name(self) -> str:
            return "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz"

        def get_os_name(self) -> str:
            return "Linux 6.12.74+deb13+1-cloud-amd64-extended"

        def get_project_version(self, _event: object) -> str:
            return "AstrBot"

        async def get_plugin_counts(self) -> int:
            return 1

        def get_net_speed_kbs(self) -> tuple[float, float]:
            return 1.0, 2.0

        def get_uptime_text(self) -> str:
            return "00:00:01"

    async def fake_html_render(*_args: object, **_kwargs: object) -> str:
        return "image-url"

    renderer = HtmlRender(
        context=SimpleNamespace(),
        config_manager=SimpleNamespace(
            banner_paths=[],
            traffic_monitor=SimpleNamespace(enabled=True),
        ),
        base_dir=ROOT,
        plugin_data_dir=ROOT,
        html_render=fake_html_render,
        data_source=FakeDataSource(),
        bot_identity_resolver=FakeResolver(),
        traffic_recorder=_FakeTrafficRecorder(),
    )

    text = await renderer.build_status_text(SimpleNamespace())

    assert "本月流量: 合计 3.0 MB，上传 1.0 MB，下载 2.0 MB" in text
    assert "CPU: Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz" in text
    assert "操作系统: Linux 6.12.74+deb13+1-cloud-amd64-extended" in text


def test_bottom_paw_decorations_remain_visible_inside_card() -> None:
    css = (ROOT / "templates/res/css/style.css").read_text(encoding="utf-8-sig")

    for class_name in ("bg-small-paw", "bg-big-paw"):
        rule = re.search(
            rf"^\s*\.{class_name}\s*\{{(?P<body>[^}}]+)\}}",
            css,
            re.MULTILINE,
        )
        assert rule is not None

        bottom = re.search(r"bottom:\s*(-?\d+)px", rule["body"])
        height = re.search(r"height:\s*(\d+)px", rule["body"])
        assert bottom is not None
        assert height is not None
        assert int(bottom.group(1)) > -int(height.group(1))


def test_t2i_render_has_no_large_white_bottom_gap() -> None:
    html, payload = _render_payload()
    post_data = {
        "tmpl": html,
        "tmpldata": payload,
        "json": True,
        "options": {"full_page": True, "type": "png", "scale": "device"},
    }

    try:
        response = requests.post(T2I_ENDPOINT, json=post_data, timeout=15)
    except requests.RequestException as exc:
        pytest.skip(f"T2I service is unavailable: {exc}")

    if response.status_code >= 500:
        pytest.skip(f"T2I service is unavailable: HTTP {response.status_code}")
    response.raise_for_status()

    image_id = response.json()["data"]["id"]
    image_url = f"http://localhost:8999/text2img/{image_id}"
    image_response = requests.get(image_url, timeout=15)
    image_response.raise_for_status()

    output_dir = ROOT / "tests" / "output"
    output_dir.mkdir(exist_ok=True)
    image_path = output_dir / "status_t2i_regression.jpg"
    image_path.write_bytes(image_response.content)

    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    bottom_band = image.crop((0, max(0, height - 160), width, height))
    pixels = list(bottom_band.get_flattened_data())
    near_white = sum(
        1 for red, green, blue in pixels if red > 245 and green > 245 and blue > 245
    )
    near_white_ratio = near_white / len(pixels)

    assert width == 500
    assert near_white_ratio < 0.2
