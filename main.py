import argparse
import sys
import json
from crawler import LeadDiscoveryCrawler
from exporters import export_all_csvs
from validate_benchmark import run_benchmark_audit
from database import get_connection, DEFAULT_DB_PATH, init_db, get_cache_stats

import io

def _setup_console_io():
    # If run in windowed mode from terminal (PowerShell / CMD), attach to parent console so CLI commands work
    if sys.platform == "win32" and (sys.stdout is None or getattr(sys.stdout, "closed", False)):
        try:
            import ctypes
            if ctypes.windll.kernel32.AttachConsole(-1):
                sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
                sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
        except Exception:
            pass

    if sys.stdout is None:
        sys.stdout = io.StringIO()
    elif hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if sys.stderr is None:
        sys.stderr = io.StringIO()
    elif hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

_setup_console_io()


def main():
    init_db(DEFAULT_DB_PATH)
    parser = argparse.ArgumentParser(description="Noavaran Panjereh Lead Discovery Scraper")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: ui
    subparsers.add_parser("ui", help="Launch the graphical user interface (GUI)")

    # Command: run
    run_parser = subparsers.add_parser("run", help="Run the autonomous lead crawler")
    run_parser.add_argument("--max-passes", type=int, default=12, help="Max search passes to execute")
    run_parser.add_argument("--streak-limit", type=int, default=4, help="Stop if 0 new entities in N passes")
    run_parser.add_argument("--budget-sec", type=int, default=180, help="Execution time budget in seconds")
    run_parser.add_argument("--channels", type=int, default=4, help="Max Telegram channels to scrape")
    run_parser.add_argument("--results-per-query", type=int, default=5, help="Search results per query")

    # Command: export
    subparsers.add_parser("export", help="Export active_projects.csv and contacts.csv from cache")

    # Command: stats
    subparsers.add_parser("stats", help="Display cache and discovery statistics")

    # Command: rebuild
    subparsers.add_parser("rebuild", help="Re-process all logged raw records and re-export clean CSVs")

    # Command: validate
    subparsers.add_parser("validate", help="Run benchmark audit against known Isfahan entities")

    # If double-clicked without arguments, launch GUI directly
    if len(sys.argv) == 1:
        from ui import launch_ui
        launch_ui()
        return

    args = parser.parse_args()

    if args.command == "ui":
        from ui import launch_ui
        launch_ui()

    elif args.command == "run":
        max_passes = getattr(args, "max_passes", 12)
        streak_limit = getattr(args, "streak_limit", 4)
        budget_sec = getattr(args, "budget_sec", 180)
        channels = getattr(args, "channels", 4)
        r_per_q = getattr(args, "results_per_query", 5)

        print("🚀 Launching Noavaran Panjereh Lead Discovery Harvester...")
        crawler = LeadDiscoveryCrawler()
        summary = crawler.run(
            max_passes=max_passes,
            streak_limit=streak_limit,
            time_budget_sec=budget_sec,
            max_telegram_channels=channels,
            max_results_per_query=r_per_q,
        )
        print("\n=== RUN SUMMARY ===")
        print(json.dumps(summary, indent=2, ensure_ascii=False))

    elif args.command == "rebuild":
        print("🔄 Re-processing all raw records with updated deduplication & normalizer logic...")
        crawler = LeadDiscoveryCrawler()
        stats = crawler.rebuild_cache_from_raw()
        print(f"Processed {stats['processed_raw_records']} raw records -> {stats['contacts_exported']} contacts, {stats['projects_exported']} active projects")
        print("Exported clean CSVs: contacts.csv, active_projects.csv")

    elif args.command == "export":
        print("📁 Exporting CSV files from persistent cache...")
        stats = export_all_csvs()
        print(f"Exported {stats['contacts_exported']} contacts to {stats['contacts_file']}")
        print(f"Exported {stats['projects_exported']} active projects to {stats['projects_file']}")

    elif args.command == "stats":
        stats = get_cache_stats(DEFAULT_DB_PATH)
        print("=== CACHE STATISTICS ===")
        print(f"Total Contacts: {stats['contacts']}")
        print(f"Total Active Projects: {stats['projects']}")
        print(f"Pre-merge Raw Records Logged: {stats['raw_records']}")
        print(f"Ambiguous Matches Flagged for Review: {stats['ambiguous_reviews']}")

    elif args.command == "validate":
        print("🔍 Running Hand-Picked Benchmark Audit...")
        report = run_benchmark_audit()
        print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
