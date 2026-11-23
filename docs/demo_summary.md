# Synthetic ledger review

Seed 0 generated 20,894 ledger lines across 7,559 vouchers. The working paper lists 50 of the 3,308 flagged vouchers.

## Reconciliation

Reconciled 24 accounts from opening balance through ledger movements to closing balance. Sum of absolute account differences was **0.00**.

## Tests and coverage

The Python checks and simulated IDEA checks ran on the same ledger.

| Test run | Vouchers flagged |
| --- | ---: |
| Benford | 1,611 |
| Duplicate | 41 |
| Ending 99/999 | 16 |
| Keyword Match | 279 |
| Manual Entry | 1,173 |
| No or Vague Narration | 163 |
| Period End | 682 |
| Public Holiday | 57 |
| Rounded Amount | 28 |
| Same User Created and Approved | 12 |
| Saturday | 17 |
| Seldom Account Entries | 17 |
| Sunday | 16 |

All selection tests ran without reported limitations.

## From voucher rank to ledger lines

Voucher **JV00206** ranked first with a score of **49.50** and an amount of **99,452.89**.

**Score breakdown** · Same User Created and Approved 7.0 + Seldom Account Entries 6.6 + Keyword Match 3.6 + date (Period End) 1.0, × amount 2.71

| Row ID | Account | Tests that flagged the line |
| --- | --- | --- |
| 4649 | Suspense Account 9 | Keyword Match, Period End, Same User Created and Approved, Seldom Account Entries |
| 4650 | Cash at Bank | Period End, Same User Created and Approved |
| 4651 | Accounts Receivable | Period End, Same User Created and Approved |
