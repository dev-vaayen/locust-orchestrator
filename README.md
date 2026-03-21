<div align=center> 

# Locust Orchestrator  
</div>

A simple python based orchestrator for Locust that allows you to input an exhaustive load-test plan and executes it sequentially one by one, while saving all of the reports in your machine, locally.

## Storytime

While using Locust, I kept thinking how cool it would be if I could just maybe input a CSV file with things like concurrent users, ramp-up and duration because till then, I had to input all of these one by one after each Load-Test's completion.

To combat this, now I make use of this orchestrator to execute all of my test-plans in the background and let the reports get been saved for a later reviews. You can use it just like Locust and pass all those arguments that you're already familiar with since this tool is also executing locust as a process, under the hood.

---

## What it does

- Execute multiple load tests from a CSV file
- Automatically generate HTML reports for each run
- Provide execution logs with timestamps
- Generate a summary JSON of all runs

---

## Installation

```
pip install locust-orchestrator
```

Or you can just execute the compiled executable file using the good old `./locust-orchestrator --plan plan.csv` method, as well. 

---

## Example CSV (plan.csv)

```
users,spawn_rate,duration,description,tags
100,10,2m,Login test,auth
500,50,5m,Search test,search
200,20,3m,Checkout test,payment
```

---

## Usage

After the creation of your test-plan, you're pretty much good to go:
```
locust_orchestrator --plan plan.csv -f locust.py --reports-dir ./results --host http://localhost:8919 --processes -1 
```

Command flags:
```
--plan FILE            Path to CSV plan (default: plan.csv)
--reports-dir DIR      Output directory for reports
--host URL             Override host for all runs
--start-at N           Resume from step N
--stop-on-failure      Stop execution if any step fails
--dry-run              Print commands without executing
--cooldown SECONDS     Delay between steps (default: 5)
```

To add to this, you can use pretty much any other flag supported by Locust, since this tool is only an added layer over it and only aims to add more functionality to it.

---

## Output

After execution:

* HTML reports per test -> `reports/`
* Log file -> `orchestrator_<timestamp>.log`

---

## Requirements

- Python 3.8+ (Recommended)
- Locust installed (pip install locust)

---

## Future Plans

For the next versions, I intend on implementing these functionalities:
- Combined report dashboard
- SQLite history tracking
- Streamlit visualization
---
