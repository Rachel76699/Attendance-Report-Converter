import os
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Protocol

from domain.models import AttendanceReport
from generation.excel_renderer import ExcelRenderer
from generation.pdf_generator import generate_pdf


class OutputRenderer(Protocol):
    def render(self, report: AttendanceReport, output_path: str) -> str: ...


class FunctionRenderer:
    def __init__(self, render_function: Callable[[AttendanceReport, str], str]):
        self._render_function = render_function

    def render(self, report: AttendanceReport, output_path: str) -> str:
        return self._render_function(report, output_path)


def _create_pdf_renderer() -> OutputRenderer:
    return FunctionRenderer(generate_pdf)


def _create_excel_renderer() -> OutputRenderer:
    return ExcelRenderer()


OUTPUT_RENDERER_FACTORIES: Mapping[str, Callable[[], OutputRenderer]] = MappingProxyType({
    ".pdf": _create_pdf_renderer,
    ".xlsx": _create_excel_renderer,
})


def _output_paths(output_dir: str, stem: str, extensions: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        os.path.join(output_dir, f"{stem}{extension}")
        for extension in extensions
    )


def _available_paths(output_dir: str, stem: str, extensions: tuple[str, ...]) -> tuple[str, ...]:
    suffix = 1
    while True:
        candidate_stem = f"{stem}_{suffix}"
        paths = _output_paths(output_dir, candidate_stem, extensions)
        if not any(os.path.exists(path) for path in paths):
            return paths
        suffix += 1


def render_outputs(
    report: AttendanceReport,
    output_dir: str,
    stem: str,
    renderer_overrides: Mapping[str, OutputRenderer] | None = None,
) -> tuple[str, ...]:
    renderers = {
        extension: factory()
        for extension, factory in OUTPUT_RENDERER_FACTORIES.items()
    }
    if renderer_overrides is not None:
        renderers.update({
            extension if extension.startswith(".") else f".{extension}": renderer
            for extension, renderer in renderer_overrides.items()
        })

    extensions = tuple(renderers)
    paths = _output_paths(output_dir, stem, extensions)
    try:
        for extension, path in zip(extensions, paths):
            renderers[extension].render(report, path)
        return paths
    except PermissionError as error:
        blocked_path = getattr(error, "filename", None)
        normalized_paths = {
            os.path.normcase(os.path.abspath(path))
            for path in paths
        }
        if (
            not blocked_path
            or os.path.normcase(os.path.abspath(blocked_path)) not in normalized_paths
        ):
            raise

        fallback_paths = _available_paths(output_dir, stem, extensions)
        print(
            "    [Warning] An existing output file is unavailable "
            "(possibly open in another program). Saving as: "
            f"{', '.join(os.path.basename(path) for path in fallback_paths)}"
        )
        for extension, path in zip(extensions, fallback_paths):
            renderers[extension].render(report, path)
        return fallback_paths
