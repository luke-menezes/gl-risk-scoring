# Synthetic ledger review

Seed 0 generated 20,051 ledger lines across 7,559 vouchers. The working paper lists 50 of the 3,289 flagged vouchers.

## Reconciliation

Reconciled 21 accounts from opening balance through ledger movements to closing balance. Sum of absolute account differences was **0.00**.

## Tests and coverage

The Python checks and simulated IDEA checks ran on the same ledger.

| Test run | Vouchers flagged |
| --- | ---: |
| Benford | 1,606 |
| Duplicate | 36 |
| Ending 99/999 | 8 |
| Keyword Match | 276 |
| Manual Entry | 1,183 |
| No or Vague Narration | 160 |
| Period End | 680 |
| Public Holiday | 57 |
| Rounded Amount | 30 |
| Same User Created and Approved | 10 |
| Saturday | 16 |
| Seldom Account Entries | 10 |
| Sunday | 15 |

All selection tests ran without reported limitations.

## From voucher rank to ledger lines

Voucher **JV05068** ranked first with a score of **53.94** and an amount of **100,000.00**.

**Score breakdown** · Same User Created and Approved 7.2 + Seldom Account Entries 7.2 + Rounded Amount 3.6 + date (Period End) 1.0 + Manual Entry 0.8, × amount 2.72

| Row ID | Account | Tests that flagged the line |
| --- | --- | --- |
| 19937 | Suspense Account 9 | Rounded Amount, Period End, Manual Entry, Same User Created and Approved, Seldom Account Entries |
| 19938 | VAT Payable | Rounded Amount, Period End, Manual Entry, Same User Created and Approved |
