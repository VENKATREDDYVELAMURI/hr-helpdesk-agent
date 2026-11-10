# Employee Helpdesk & Payroll Query Agent (HR Shared Services)

Group 15, Agentic AI for Business Operations, Woxsen University, School of Business (MBA Trimester 4, 2026-2027).

All data are synthetic. No real employee or company data are used.

## What is in this repository

| File | Purpose |
|---|---|
| `hr_proto.py` | Tool and guardrail layer: identity-scoped read tools (`get_payslip`, `compare_months`, `get_leave_balance`), `create_ticket`, variance arithmetic check, input filter, retrieved-document filter, deny-list, PII scan, retry and escalation logic, audit log |
| `run_tests.py` | Runs the deterministic checks T2 to T6, T8, T10 and T11 from Table 4.6 of the report |
| `eval/test_output.txt` | Recorded output of the last run (9 of 9 checks passed) |

## Status

- Done: tool and guardrail layer and its tests.
- Still to build and run: the LLM agents (Supervisor, Policy, Payroll and HRIS, Verifier, Case), the policy vector store, the Streamlit chat and HR console, and the 150-case end-to-end evaluation. Cases T1, T7, T9 and T12 need the live model.

## Setup

1. Python 3.11 or later.
2. `python run_tests.py`  (no packages needed for the current layer).
3. For the LLM agents: create a `.env` file with your model provider API key (never commit it) and install the packages listed in `requirements.txt`.

## Architecture

Supervisor-worker multi-agent graph (LangGraph) with a Verifier and a Case Agent; see Chapter 3 of the report.
