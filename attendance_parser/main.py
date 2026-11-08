import sys

from application import (
    collect_pdf_files,
    parse_arguments,
    prepare_paths,
    process_single_pdf,
    print_summary,
)


def main() -> int:
    # 1. Read command-line options.
    args = parse_arguments()

    # 2. Validate paths and prepare the output directory.
    paths = prepare_paths(args.input, args.output)
    if paths is None:
        return 1
    source, output = paths

    # 3. Find reports and process each PDF.
    files = collect_pdf_files(source)
    if not files:
        print(f"[Info] No PDF files found in {source}")
        return 1
    results = [process_single_pdf(path, output) for path in files]

    # 4. Print the result summary.
    print_summary(files, results, output)
    return int(not all(results))


if __name__ == "__main__":
    sys.exit(main())
