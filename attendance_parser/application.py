import argparse
import os
from collections.abc import Callable
from typing import Protocol

from domain.exceptions import AttendanceConverterError
from domain.models import AttendanceReport
from generation import output_registry
from parsing import classifier, ocr, parser_factory
from transformation import strategies


class ReportTransformer(Protocol):
    def transform(self, report: AttendanceReport) -> AttendanceReport: ...


class ExcelReportRenderer(Protocol):
    def render(self, report: AttendanceReport, output_path: str) -> str: ...


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Attendance Report Generator")
    parser.add_argument(
        "input", nargs="?", default="data/sample_reports",
        help="Input PDF or directory",
    )
    parser.add_argument(
        "-o", "--output", default="data/output_reports",
        help="Output directory",
    )
    parser.add_argument(
        "--force-ocr", action="store_true",
        help="Re-extract PDF text instead of using the OCR text cache",
    )
    return parser.parse_args()


def prepare_paths(input_path: str, output_path: str) -> tuple[str, str] | None:
    source = os.path.abspath(input_path)
    output = os.path.abspath(output_path)
    if not os.path.exists(source):
        print(f"[Error] Input path does not exist: {source}")
        return None
    if os.path.isfile(source) and not source.lower().endswith(".pdf"):
        print("[Error] Input file must be a PDF.")
        return None
    os.makedirs(output, exist_ok=True)
    return source, output


def collect_pdf_files(source: str) -> list[str]:
    if os.path.isfile(source):
        return [source]
    if os.path.isdir(source):
        return [
            os.path.join(source, name)
            for name in sorted(os.listdir(source))
            if name.lower().endswith(".pdf")
        ]
    return []


def _generate_outputs(
    report: AttendanceReport,
    output_dir: str,
    stem: str,
    pdf_renderer: Callable[[AttendanceReport, str], str] | None = None,
    excel_report_renderer: ExcelReportRenderer | None = None,
) -> tuple[str, ...]:
    overrides = {}
    if pdf_renderer is not None:
        overrides[".pdf"] = output_registry.FunctionRenderer(pdf_renderer)
    if excel_report_renderer is not None:
        overrides[".xlsx"] = excel_report_renderer
    return output_registry.render_outputs(
        report,
        output_dir,
        stem,
        renderer_overrides=overrides,
    )


def process_single_pdf(
    input_path: str,
    output_dir: str,
    force_ocr: bool = False,
    transformation_service: ReportTransformer | None = None,
    pdf_renderer: Callable[[AttendanceReport, str], str] | None = None,
    excel_report_renderer: ExcelReportRenderer | None = None,
) -> bool:
    filename = os.path.basename(input_path)
    stem = os.path.splitext(filename)[0]
    output_stem = f"NEW_{stem}"
    print(f"\n[+] Processing: {filename}")
    try:
        raw_text = ocr.extract_text_from_pdf(input_path, force_ocr=force_ocr)
        if not raw_text or not raw_text.strip():
            print(f"[Error] No text extracted from {filename}")
            return False
        report_type = classifier.classify_report_type(raw_text)
        if report_type is None:
            print(
                f"[Error] {filename} was not recognized as an attendance report "
                "(supported formats: Type A or Type B). No output was generated."
            )
            return False
        report = parser_factory.get_parser(report_type).parse(raw_text)
        if not report.rows:
            print(
                f"[Error] No attendance rows were found in {filename}. "
                "The file may not be a supported attendance report. "
                "No output was generated."
            )
            return False
        transformer = transformation_service
        if transformer is None:
            transformer = strategies.TransformationService(seed=42)
        report = transformer.transform(report)
        os.makedirs(output_dir, exist_ok=True)
        saved_paths = _generate_outputs(
            report,
            output_dir,
            output_stem,
            pdf_renderer=pdf_renderer,
            excel_report_renderer=excel_report_renderer,
        )
        print(f"    [Success] Saved to: {', '.join(saved_paths)}")
        return True
    except (AttendanceConverterError, OSError, RuntimeError, ValueError) as error:
        print(f"    [Error] Failed to process {filename}: {error}")
        return False


def print_summary(files: list[str], results: list[bool], output: str) -> None:
    successful = sum(results)
    failed = len(files) - successful
    width = 38
    border = "+" + "-" * (width - 2) + "+"
    print(f"\n{border}")
    print(f"|{'PROCESSING SUMMARY':^{width - 2}}|")
    print(border)
    print(f"| {'Reports processed':<20}: {len(files):>{width - 26}} |")
    print(f"| {'Successful':<20}: {successful:>{width - 26}} |")
    print(f"| {'Failed':<20}: {failed:>{width - 26}} |")
    print(border)
    print(f"Output directory:\n  {output}")
