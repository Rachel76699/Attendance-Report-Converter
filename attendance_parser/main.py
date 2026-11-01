import os
import argparse
import traceback

from parsing.ocr import extract_text_from_pdf
from parsing.classifier import classify_report_type
from parsing.parser_factory import get_parser
from transformation.strategies import TransformationService
from generation.pdf_generator import generate_pdf


def process_single_pdf(input_path: str, output_dir: str):
    """Process one PDF report."""

    filename = os.path.basename(input_path)
    base_name, _ = os.path.splitext(filename)

    output_filename = f"NEW_{base_name}.pdf"
    output_path = os.path.join(output_dir, output_filename)

    print(f"\n[+] Processing: {filename}")

    try:
        # 1. Extract text from PDF using OCR / Poppler
        raw_text = extract_text_from_pdf(input_path)

        if not raw_text or not raw_text.strip():
            print(f"[Error] No text extracted from {filename}")
            return False

        # 2. Classify report type
        report_type = classify_report_type(raw_text)
        print(f"    [Type] {report_type}")

        # 3. Get the appropriate parser
        parser = get_parser(report_type)

        # 4. Parse extracted text into domain model
        report = parser.parse(raw_text)

        # 5. Transform report (Deterministic variation)
        transformer = TransformationService(seed=42)
        transformed_report = transformer.transform(report)

        # 6. Create output directory if needed
        os.makedirs(output_dir, exist_ok=True)

        # 7. Generate new PDF
        generate_pdf(transformed_report, output_path)

        print(f"    [Success] Saved to: {output_path}")
        return True

    except Exception as e:
        print(f"    [Error] Failed to process {filename}: {e}")
        traceback.print_exc()
        return False


def main():
    """Main application pipeline."""

    parser = argparse.ArgumentParser(
        description="Attendance Report Generator"
    )

    parser.add_argument(
        "input",
        nargs="?",
        default="data/sample_reports",
        help="Path to input PDF file or directory"
    )

    parser.add_argument(
        "-o",
        "--output",
        default="data/output_reports",
        help="Output directory"
    )

    args = parser.parse_args()

    input_path = os.path.abspath(args.input)
    output_dir = os.path.abspath(args.output)

    # Check that input exists
    if not os.path.exists(input_path):
        print(f"[Error] Input path does not exist: {input_path}")
        return

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    # Process a single PDF
    if os.path.isfile(input_path):

        if not input_path.lower().endswith(".pdf"):
            print("[Error] Input file must be a PDF.")
            return

        success = process_single_pdf(input_path, output_dir)
        print("\nFinished.")
        print(f"Successful files: {1 if success else 0}")
        print(f"Failed files: {0 if success else 1}")

    # Process all PDFs in directory
    elif os.path.isdir(input_path):

        pdf_files = [
            f for f in os.listdir(input_path)
            if f.lower().endswith(".pdf")
        ]

        if not pdf_files:
            print(f"[Info] No PDF files found in {input_path}")
            return

        print(f"\nFound {len(pdf_files)} PDF files.")

        successful = 0
        failed = 0

        for filename in pdf_files:
            file_path = os.path.join(input_path, filename)

            if process_single_pdf(file_path, output_dir):
                successful += 1
            else:
                failed += 1

        print("\n========== SUMMARY ==========")
        print(f"Total files: {len(pdf_files)}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Output directory: {output_dir}")
        print("=============================")

    else:
        print("[Error] Input path is neither a file nor a directory.")


if __name__ == "__main__":
    main()