"""Small command line viewer for the /result observer."""
import argparse
import json
import observer


def print_matrix():
    for row in observer.get_matrix():
        print("state: " + row["state"])
        print("  meaning: " + row["meaning"])
        print("  example: " + json.dumps(row["example"], sort_keys=True))
        print("  next: " + row["next_action"])


def print_checklist(poll_interval, max_attempts):
    for line in observer.generate_checklist(poll_interval, max_attempts):
        print(line)


def run_filter(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    result = observer.filter_room_log(text)
    print("total: " + str(result["total"]))
    print("kept: " + str(result["kept_count"]))
    print("skipped_heartbeat: " + str(result["skipped_heartbeat"]))
    print("skipped_other: " + str(result["skipped_other"]))
    for line in result["kept"][:50]:
        print("KEEP: " + line[:200])
    warnings = observer.find_secret_warnings(text)
    if warnings:
        print("warning: possible secrets on lines: " + str(warnings[:10]))
        print("redact before sharing")


def run_scan(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    summary = observer.scan_result_log(text)
    print("total /result: " + str(summary["total"]))
    print("counts: " + json.dumps(summary["counts"], sort_keys=True))
    for item in summary["invocations"][:50]:
        print(str(item["line_no"]) + " [" + item["state"] + "] " + item["excerpt"][:160])
    warnings = observer.find_secret_warnings(text)
    if warnings:
        print("warning: possible secrets on lines: " + str(warnings[:10]))


def main():
    parser = argparse.ArgumentParser(description="Observe /result expected behavior")
    parser.add_argument("--matrix", action="store_true", help="print matrix")
    parser.add_argument("--checklist", action="store_true", help="print checklist")
    parser.add_argument("--poll-interval", type=int, default=5)
    parser.add_argument("--max-attempts", type=int, default=6)
    parser.add_argument("--filter", dest="filter_path", default=None)
    parser.add_argument("--scan", dest="scan_path", default=None)
    args = parser.parse_args()
    if args.matrix:
        print_matrix()
        return
    if args.checklist:
        print_checklist(args.poll_interval, args.max_attempts)
        return
    if args.filter_path:
        run_filter(args.filter_path)
        return
    if args.scan_path:
        run_scan(args.scan_path)
        return
    parser.print_help()


if __name__ == "__main__":
    main()
