import csv
import glob
import os
import sys

OUTPUT_FIELDS = [
    "query",
    "source_type",
    "document_type",
    "title",
    "source_name",
    "source_domain",
    "url",
    "local_path",
    "file_type",
    "matched_keywords",
    "snippet",
    "published_hint",
    "priority_score",
    "priority",
    "query_family",
    "legacy_key",
    "repo",
    "repo_name",
    "org",
    "org_type",
    "contributor_count",
    "language",
    "stars",
    "username",
    "display_name",
    "email",
    "company",
    "bio",
    "location",
    "github_profile",
    "linkedin",
    "twitter",
    "blog",
    "commit_message",
    "commit_url",
    "commit_date",
]


def row_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        (row.get("query") or "").strip(),
        (row.get("url") or "").strip(),
        (row.get("local_path") or "").strip(),
    )


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python merge_results.py <results_dir> <output_csv>", file=sys.stderr)
        sys.exit(1)

    results_dir = sys.argv[1]
    output_path = sys.argv[2]
    csv_files = glob.glob(os.path.join(results_dir, "*.csv"))
    if not csv_files:
        print(f"ERROR: no *.csv files found in {results_dir}", file=sys.stderr)
        sys.exit(1)

    seen: dict[tuple[str, str, str], dict[str, str]] = {}
    total_read = 0

    print("=== Merge Results ===")
    print(f"  Input dir : {results_dir}")
    print(f"  CSV files : {len(csv_files)}")
    print(f"  Output    : {output_path}")
    print()

    for path in sorted(csv_files):
        file_count = 0
        try:
            with open(path, newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    total_read += 1
                    file_count += 1
                    seen.setdefault(row_key(row), row)
        except Exception as exc:
            print(f"  [warn] could not read {path}: {exc}")
            continue
        print(f"  read {file_count:>5} rows from {os.path.basename(path)}")

    merged_rows = list(seen.values())
    merged_rows.sort(key=lambda row: int(row.get("priority_score") or 0), reverse=True)

    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in merged_rows:
            writer.writerow({field: row.get(field, "") for field in OUTPUT_FIELDS})

    p1 = sum(1 for row in merged_rows if row.get("priority") == "P1")
    p2 = sum(1 for row in merged_rows if row.get("priority") == "P2")
    p3 = sum(1 for row in merged_rows if row.get("priority") == "P3")

    print(f"\n  total read   : {total_read}")
    print(f"  unique docs  : {len(merged_rows)}")
    print(f"  deduplicated : {total_read - len(merged_rows)}")
    print(f"\n=== Summary ===")
    print(f"  P1 : {p1}")
    print(f"  P2 : {p2}")
    print(f"  P3 : {p3}")
    print(f"\n  Written to : {output_path}")


if __name__ == "__main__":
    main()
