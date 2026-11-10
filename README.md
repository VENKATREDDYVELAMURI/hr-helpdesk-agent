# Employee Helpdesk & Payroll Query Agent (HR Shared Services)

Group 15, Agentic AI for Business Operations, Woxsen University, School of Business (MBA Trimester 4, 2026-2027).

All data are synthetic. No real employee or company data are used.

## What is in this repository

| File | Purpose |
|---|---|
| `hr_proto.py` | Tool and guardrail layer: identity-scoped read tools (`get_payslip`, `compare_months`, `get_leave_balance`), `create_ticket`, variance arithmetic check, TF-IDF policy retrieval, input filter, retrieved-document filter, deny-list, PII scan, sensitive-topic check, rule-based router, retry and escalation logic, audit log |
| `run_tests.py` | Runs 17 automated checks (T1 to T12, R1 to R6) from Table 4.6 of the report |
| `robustness.py` | Five paraphrased attacks used to test the input filter (before and after the fix are in `eval/`) |
| `eval/` | Recorded outputs: `test_output.txt` (17 of 17 checks passed), `robustness_before.txt` (3 of 5 caught), `robustness_after.txt` (5 of 5 caught) |

## Status

- Done: tool, retrieval and guardrail layer and its 17 automated checks.
- Still to build and run: the LLM agents (Supervisor, Policy, Payroll and HRIS, Verifier, Case), the policy vector store, the Streamlit chat and HR console, and the 150-case end-to-end evaluation. The checks in `run_tests.py` cover the rule layer only; how well the model writes answers is not yet tested.

## Setup

1. Python 3.11 or later.
2. `python run_tests.py`  (no packages needed for the current layer).
3. For the LLM agents: create a `.env` file with your model provider API key (never commit it) and install the packages listed in `requirements.txt`.

## Architecture

Supervisor-worker multi-agent graph (LangGraph) with a Verifier and a Case Agent; see Chapter 3 of the report.
