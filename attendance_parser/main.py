import sys

from application import (
    collect_pdf_files,
    parse_arguments,
    prepare_paths,
    process_single_pdf,
    print_summary,
)
from transformation.strategies import TransformationService


def main() -> int:
    args = parse_arguments()
    paths = prepare_paths(args.input, args.output)
    if paths is None:
        return 1
    source, output = paths
    files = collect_pdf_files(source)
    if not files:
        print(f"[Info] No PDF files found in {source}")
        return 1
    transformation_service = TransformationService(seed=42)
    results = [
        process_single_pdf(
            path,
            output,
            force_ocr=args.force_ocr,
            transformation_service=transformation_service,
        )
        for path in files
    ]
    print_summary(files, results, output)
    return int(not all(results))

if __name__ == "__main__":
    sys.exit(main())
