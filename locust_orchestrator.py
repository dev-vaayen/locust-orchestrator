import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# -- ANSI colours (disabled automatically when not a TTY) ---------------------
# check if we're in a real terminal or some garbage output thingy
_IS_TTY = sys.stdout.isatty()

# helper function to add colors to text if we can
def _c(code: str, text: str) -> str:
    # if it's a real terminal add the color codes, otherwise just return plain text
    return f"\033[{code}m{text}\033[0m" if _IS_TTY else text

# these are just shortcuts for different colors so we don't have to remember the codes
def green(t):   return _c("32", t)  # makes stuff green
def yellow(t):  return _c("33", t)  # makes stuff yellow
def red(t):     return _c("31", t)  # makes stuff red
def cyan(t):    return _c("36", t)  # makes stuff cyan
def bold(t):    return _c("1",  t)  # makes stuff bold
def dim(t):     return _c("2",  t)  # makes stuff dim/light


# -- Logging ------------------------------------------------------------------
# where we write the logs to file if we need to
_log_file = None

# get current time as a string for log messages
def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# main logging function - prints to screen and also to file if we set one up
def log(msg: str, level: str = "INFO") -> None:
    line = f"[{_ts()}] [{level:<7}] {msg}"
    print(line)  # show it on screen
    if _log_file:  # if we have a log file, write it there too
        with open(_log_file, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

# these are just wrappers for different log levels so we don't have to type the level every time
def log_info(msg):    log(msg, "INFO")
def log_ok(msg):      log(green(msg), "OK")  # green means good news!
def log_warn(msg):    log(yellow(msg), "WARN")  # yellow means careful
def log_error(msg):   log(red(msg), "ERROR")  # red means bad stuff happened
def log_header(msg):  log(bold(cyan(msg)), "-----")  # headers look fancy


# -- CSV parsing ---------------------------------------------------------------
# these are the columns we absolutely need in the CSV file
REQUIRED_COLS = {"users", "spawn_rate", "duration"}

# reads the CSV file and checks if it has everything we need
def load_plan(csv_path: Path) -> list[dict]:
    # make sure the file exists before we try to read it
    if not csv_path.exists():
        log_error(f"Plan file not found: {csv_path}")
        sys.exit(1)  # exit if file doesn't exist, no point continuing

    rows = []  # this will hold all our test steps
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)  # reads CSV into dictionaries
        if reader.fieldnames is None:  # if file is empty or has no headers
            log_error("CSV file appears empty.")
            sys.exit(1)

        # check if we have all required columns
        cols = {c.strip().lower() for c in reader.fieldnames}
        missing = REQUIRED_COLS - cols
        if missing:
            log_error(f"CSV is missing required columns: {missing}")
            sys.exit(1)

        # go through each row and make sure numbers are actually numbers
        for i, raw in enumerate(reader, start=2):  # row 2 is first data row cause row1 is header
            row = {k.strip().lower(): v.strip() for k, v in raw.items()}
            # check if users and spawn_rate are valid integers
            for field in ("users", "spawn_rate"):
                try:
                    int(row[field])
                except ValueError:
                    log_error(f"Row {i}: '{field}' must be an integer, got: {row[field]!r}")
                    sys.exit(1)
            rows.append(row)

    # make sure we actually got some data
    if not rows:
        log_error("Plan CSV has no data rows.")
        sys.exit(1)

    return rows


# -- Command builder -----------------------------------------------------------
# builds the command line to run locust for a specific step
def build_command(
    row: dict,
    report_path: Path,
    host: str | None,
    extra_args: list[str],
) -> list[str]:
    # get locustfile from CSV or use default if not specified
    locustfile = row.get("locustfile", "").strip() or "locustfile.py"
    users      = row["users"]
    spawn_rate = row["spawn_rate"]
    duration   = row.get("duration", "5m").strip() or "5m"  # default 5 minutes
    tags       = row.get("tags", "").strip()

    # start building the command
    cmd = [
        sys.executable, "-m", "locust",  # run locust as a module
        "-f",  locustfile,               # which locustfile to use
        "--headless",                    # no web UI, just run and exit
        "-u",  users,                    # number of users
        "-r",  spawn_rate,               # how fast to spawn them
        "-t",  duration,                 # how long to run
        "--html", str(report_path),      # where to save the HTML report
    ]

    # if we have a host override, add it to the command
    if host:
        cmd += ["--host", host]

    # if there are tags, add them to the command
    if tags:
        cmd += ["--tags"] + [t.strip() for t in tags.split(",") if t.strip()]

    # add any extra arguments that were passed from the command line
    cmd += extra_args
    return [str(c) for c in cmd]  # make sure everything is string


# -- Pretty-print a plan row ---------------------------------------------------
# makes a nice description of what we're about to run
def describe_row(index: int, total: int, row: dict) -> str:
    desc = row.get("description", "").strip()  # get description if exists
    tags = row.get("tags", "").strip()         # get tags if exists
    tag_str = f"  tags=[{tags}]" if tags else ""
    return (
        f"Step {index}/{total}: "
        f"users={bold(row['users'])}  "
        f"spawn_rate={bold(row['spawn_rate'])}/s  "
        f"duration={bold(row.get('duration','5m'))}"
        f"{tag_str}"
        + (f"  — {dim(desc)}" if desc else "")
    )


# -- Single run executor -------------------------------------------------------
# actually runs one locust test step
def run_step(
    index: int,
    total: int,
    row: dict,
    reports_dir: Path,
    host: str | None,
    extra_args: list[str],
    dry_run: bool,
) -> dict:
    """Execute one locust run and return a result dict."""
    # create a timestamp for the report filename
    ts_label = datetime.now().strftime("%Y%m%d_%H%M%S")
    # build a unique filename so we don't overwrite stuff
    report_name = (
        f"report_step{index:03d}"
        f"_u{row['users']}"
        f"_r{row['spawn_rate']}"
        f"_t{row.get('duration','5m').replace('m','min').replace('s','sec')}"
        f"_{ts_label}.html"
    )
    report_path = reports_dir / report_name
    # build the command we're gonna run
    cmd = build_command(row, report_path, host, extra_args)

    # show what we're about to do
    log_header("-" * 60)
    log_info(describe_row(index, total, row))
    log_info(f"Report  → {report_path.name}")
    log_info(f"Command → {' '.join(cmd)}")
    log_header("-" * 60)

    # create a result dictionary with all the info about this step
    result = {
        "step":        index,
        "users":       row["users"],
        "spawn_rate":  row["spawn_rate"],
        "duration":    row.get("duration", "5m"),
        "description": row.get("description", ""),
        "tags":        row.get("tags", ""),
        "command":     " ".join(cmd),
        "report_file": report_name,
        "status":      "skipped",  # placeholder, will update later
        "exit_code":   None,
        "elapsed_s":   None,
        "started_at":  None,
        "finished_at": None,
        "error":       None,
    }

    # if it's just a dry run, don't actually run anything
    if dry_run:
        log_warn("DRY RUN — skipping execution.")
        result["status"] = "dry_run"
        return result

    # remember when we started
    started = datetime.now()
    result["started_at"] = started.isoformat()

    try:
        # actually run the command
        proc = subprocess.run(cmd, check=False)
        exit_code = proc.returncode  # get the exit code
    except FileNotFoundError as exc:
        # if locust isn't installed or something
        log_error(f"Could not launch locust: {exc}")
        result["status"] = "launch_error"
        result["error"]  = str(exc)
        result["finished_at"] = datetime.now().isoformat()
        result["elapsed_s"]   = (datetime.now() - started).total_seconds()
        return result
    except KeyboardInterrupt:
        # user pressed Ctrl+C
        log_warn("Interrupted by user — stopping orchestrator.")
        result["status"]      = "interrupted"
        result["finished_at"] = datetime.now().isoformat()
        result["elapsed_s"]   = (datetime.now() - started).total_seconds()
        raise  # propagate so outer loop can write summary

    # calculate how long it took
    finished = datetime.now()
    elapsed  = (finished - started).total_seconds()
    result["exit_code"]   = exit_code
    result["finished_at"] = finished.isoformat()
    result["elapsed_s"]   = round(elapsed, 1)

    # check if it worked
    if exit_code == 0:
        if report_path.exists():
            log_ok(f"✓ Step {index} passed  ({elapsed:.0f}s)  report saved: {report_name}")
            result["status"] = "passed"
        else:
            # weird case where locust says it worked but no report was created
            log_warn(f"Locust exited 0 but report not found: {report_path}")
            result["status"] = "no_report"
    else:
        log_error(f"✗ Step {index} FAILED  exit_code={exit_code}  ({elapsed:.0f}s)")
        result["status"] = "failed"

    return result


# -- Summary writer ------------------------------------------------------------
# writes a summary JSON file with all the results
def write_summary(results: list[dict], reports_dir: Path) -> Path:
    total   = len(results)
    passed  = sum(1 for r in results if r["status"] == "passed")
    failed  = sum(1 for r in results if r["status"] == "failed")
    skipped = total - passed - failed  # the rest are skipped

    # make the summary dictionary
    summary = {
        "generated_at": datetime.now().isoformat(),
        "total_steps":  total,
        "passed":       passed,
        "failed":       failed,
        "skipped":      skipped,
        "results":      results,
    }

    # save it to a file with timestamp
    summary_path = reports_dir / f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    # print a nice summary to the console
    log_header("=" * 60)
    log_info(f"SUMMARY  total={total}  passed={green(str(passed))}  failed={red(str(failed))}  skipped={yellow(str(skipped))}")
    log_info(f"Summary JSON → {summary_path}")
    log_header("=" * 60)
    return summary_path


# -- CLI -----------------------------------------------------------------------
# parse command line arguments
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Locust Orchestrator — run a CSV load-test plan sequentially.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--plan", "-p",
        default="plan.csv",
        metavar="FILE",
        help="Path to the CSV plan file (default: plan.csv)",
    )
    p.add_argument(
        "--reports-dir", "-o",
        default="reports",
        metavar="DIR",
        help="Directory where HTML reports are saved (default: ./reports)",
    )
    p.add_argument(
        "--host",
        default=None,
        metavar="URL",
        help="Override --host passed to every locust run (e.g. https://staging.example.com)",
    )
    p.add_argument(
        "--start-at",
        default=1,
        type=int,
        metavar="N",
        help="Start from step N (1-indexed). Useful to resume after a failure.",
    )
    p.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Abort the entire plan if any step exits non-zero.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the commands that would be executed without running them.",
    )
    p.add_argument(
        "--cooldown",
        default=5,
        type=int,
        metavar="SECONDS",
        help="Seconds to wait between steps (default: 5).",
    )
    p.add_argument(
        "--log-file",
        default=None,
        metavar="FILE",
        help="Also write log output to this file (default: orchestrator_<ts>.log in reports-dir).",
    )
    # any extra arguments that locust understands will be captured here
    args, extra = p.parse_known_args()
    args.extra = extra
    return args


# -- Main ----------------------------------------------------------------------
# the main function that does everything
def main() -> None:
    global _log_file  # we need to modify the global log file variable

    args = parse_args()  # get all the command line arguments

    # make sure the reports directory exists
    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    # set up the log file
    if args.log_file:
        _log_file = Path(args.log_file)
    else:
        _log_file = reports_dir / f"orchestrator_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    # load the plan from CSV
    plan_path = Path(args.plan)
    plan      = load_plan(plan_path)
    total     = len(plan)

    # check if start-at is valid
    start_at = max(1, args.start_at)
    if start_at > total:
        log_error(f"--start-at {start_at} exceeds total plan steps ({total}).")
        sys.exit(1)

    # print all the configuration so the user knows what's happening
    log_header("=" * 60)
    log_info(f"Locust Orchestrator")
    log_info(f"Plan          : {plan_path.resolve()}")
    log_info(f"Total steps   : {total}")
    log_info(f"Starting at   : step {start_at}")
    log_info(f"Reports dir   : {reports_dir.resolve()}")
    log_info(f"Log file      : {_log_file}")
    log_info(f"Host override : {args.host or '(none — use locustfile default)'}")
    log_info(f"Cooldown      : {args.cooldown}s between steps")
    log_info(f"Stop on fail  : {args.stop_on_failure}")
    log_info(f"Dry run       : {args.dry_run}")
    log_info(f"Extra → locust: {' '.join(args.extra) if args.extra else '(none)'}")
    log_header("=" * 60)

    # check if locust is installed (skip if dry run)
    if not args.dry_run:
        if not shutil.which("locust") and subprocess.run(
            [sys.executable, "-m", "locust", "--version"],
            capture_output=True,
        ).returncode != 0:
            log_error(
                "Cannot find locust. Install it with:  pip install locust"
            )
            sys.exit(1)

    results: list[dict] = []  # will store results from all steps
    orchestrator_start = datetime.now()  # remember when we started

    try:
        # go through each step in the plan
        for abs_index, row in enumerate(plan, start=1):
            # skip steps before start_at
            if abs_index < start_at:
                log_info(dim(f"Skipping step {abs_index} (--start-at={start_at})"))
                # add a skipped result entry
                results.append({
                    "step": abs_index, "status": "skipped",
                    "users": row["users"], "spawn_rate": row["spawn_rate"],
                    "duration": row.get("duration","5m"),
                    "description": row.get("description",""),
                    "tags": row.get("tags",""),
                    "command": "", "report_file": "",
                    "exit_code": None, "elapsed_s": None,
                    "started_at": None, "finished_at": None, "error": None,
                })
                continue

            # run the step
            result = run_step(
                index      = abs_index,
                total      = total,
                row        = row,
                reports_dir= reports_dir,
                host       = args.host,
                extra_args = args.extra,
                dry_run    = args.dry_run,
            )
            results.append(result)

            # if we should stop on failure and this step failed, break out
            if args.stop_on_failure and result["status"] == "failed":
                log_error(f"--stop-on-failure set — aborting after step {abs_index}.")
                break

            # wait a bit before next step (unless it's the last one)
            if abs_index < total and not args.dry_run and result["status"] not in ("launch_error",):
                log_info(f"Cooling down for {args.cooldown}s …")
                time.sleep(args.cooldown)

    except KeyboardInterrupt:
        log_warn("Orchestrator interrupted by user.")

    # show how long everything took
    elapsed_total = (datetime.now() - orchestrator_start).total_seconds()
    log_info(f"Total orchestrator time: {timedelta(seconds=int(elapsed_total))}")

    # write the summary file
    write_summary(results, reports_dir)


# run the main function if this script is executed directly
if __name__ == "__main__":
    main()
