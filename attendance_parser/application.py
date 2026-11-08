import argparse
import os
import traceback

from generation import excel_renderer, pdf_generator
from parsing import classifier, ocr, parser_factory
from transformation import strategies


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


def process_single_pdf(input_path: str, output_dir: str) -> bool:
    filename = os.path.basename(input_path)
    stem = os.path.splitext(filename)[0]
    pdf_path = os.path.join(output_dir, f"NEW_{stem}.pdf")
    excel_path = os.path.join(output_dir, f"NEW_{stem}.xlsx")
    print(f"\n[+] Processing: {filename}")
    try:
        raw_text = ocr.extract_text_from_pdf(input_path)
        if not raw_text or not raw_text.strip():
            print(f"[Error] No text extracted from {filename}")
            return False
        report_type = classifier.classify_report_type(raw_text)
        report = parser_factory.get_parser(report_type).parse(raw_text)
        report = strategies.TransformationService(seed=42).transform(report)
        os.makedirs(output_dir, exist_ok=True)
        pdf_generator.generate_pdf(report, pdf_path)
        excel_renderer.ExcelRenderer().render(report, excel_path)
        print(f"    [Success] Saved to: {pdf_path} and {excel_path}")
        return True
    except Exception as error:
        print(f"    [Error] Failed to process {filename}: {error}")
        traceback.print_exc()
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
