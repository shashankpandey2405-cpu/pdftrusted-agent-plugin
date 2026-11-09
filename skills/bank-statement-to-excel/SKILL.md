---
name: bank-statement-to-excel
description: Convert a bank or credit-card statement PDF into Excel where every transaction is checked against the balances printed on the statement (PDFTrusted). Use when the user wants a statement, passbook or card statement as Excel/CSV/rows for accounting, reconciliation, a loan or visa file, tax, GST or bookkeeping — or asks whether the totals of a statement add up.
---

# Bank statement → verified Excel (PDFTrusted API)

Client: `python <base>/../../scripts/pdftrusted.py` (see the `pdf-tools` skill for setup and limits).

The point of this tool is **trust**: a row is `VERIFIED` only when the statement's own balances prove it
(previous balance + money in − money out = printed balance, to the paisa/cent), or, for a card, when the account
summary adds up. Everything else is `NEEDS_REVIEW` with a reason code. A person's approval makes a row `REVIEWED` —
never `VERIFIED`. Keep that distinction in everything you tell the user.

## Steps

1. **Read and check** (one job):
   `pdftrusted.py statement <file.pdf>`
   You get `state`, `reasons`, `rows`, `rows_verified`, `needs_check` (only the rows that are not verified, with
   date, description, amounts, page and reason codes) and `task_id`.
   - A password-protected statement: ask the user for the password, then unlock it first with
     `pdftrusted.py run unlock <file> --opt password="..."` and use the unlocked copy. Never store the password.
   - `NO_TEXT_LAYER` / `no_text_layer`: it is a scan; ask for the PDF downloaded from net banking or the bank app.

2. **Tell the user the result in plain words.**
   - `VERIFIED`: "Every balance checks out (N of N rows)." Go to step 4 with no review.
   - `NEEDS_REVIEW`: say how many rows need a check and why, in plain words (codes below). Show the `needs_check`
     rows as a short table: row number, date, description, money out, money in, balance, reason.

3. **Fix with the user, never on your own.** For each flagged row, ask the user what the right value is (they can
   look at page `page` of their PDF) or whether to approve it as it is. Build a review file from their answers:
   ```json
   {"by": "<user's name or 'Reviewer'>",
    "corrections": [{"row": 2, "field": "debit", "value": "450.38"}],
    "approve": [2, 5]}
   ```
   Fields: `date` (YYYY-MM-DD), `description`, `debit`, `credit`, `balance` (plain numbers, dot decimal).
   Row numbers are the `row` values from `needs_check` (0-based). Do not invent corrections from arithmetic alone:
   a mismatch can be a misprinted amount *or* a misprinted balance — only the user's statement can say which.

4. **Download the Excel** — free when it uses the same file within an hour (it counts with the reading):
   `pdftrusted.py statement <file.pdf> --xlsx --review-of <task_id> [--review review.json] [-o out.xlsx]`
   The result reports `state` (`VERIFIED` or `REVIEWED`). The workbook has a Check column on every row, a Summary,
   the Sources sheet (where each value was read on the page) and, after a review, a Review log.

## Reason codes in plain words

ROWS_MISMATCH: some balances do not add up · TOTALS_DO_NOT_CLOSE: opening + in − out ≠ closing ·
OPENING_OR_CLOSING_MISSING · LAST_BALANCE_NOT_CLOSING · PRINTED_TOTALS_DIFFER: rows ≠ the totals printed ·
DATES_UNREADABLE / AMOUNTS_UNREADABLE · OVERLAPPING_TEXT: other text overlaps a row, check its description ·
CARD_SUMMARY_DOES_NOT_ADD_UP / CARD_ROWS_DIFFER / CARD_TOTALS_UNCHECKED (credit cards) · SIGN_RULE_UNPROVEN: money
in/out read from a sign, not proven by balances · UNSUPPORTED_VALUE(S): a value could not be found on the page again ·
NO_TRANSACTIONS · NO_TEXT_LAYER (scan).

## Privacy

Statements are personal financial data. Do not paste full statements into the chat, do not save extra copies, and
offer `pdftrusted.py delete <task_id>` when the user is done (otherwise the server copy is deleted within an hour).
