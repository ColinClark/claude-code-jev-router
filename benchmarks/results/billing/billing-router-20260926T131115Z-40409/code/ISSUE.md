# #231: Invoice total off by a cent; plan change on Jan 31 crashes

Two customer reports this week:

1. **INV-2041.** One line, quantity 3 at unit price 4.175, no tax. The invoice shows a subtotal of 12.52;
   finance says our rounding policy gives 12.53.
2. **Plan upgrade crash.** A customer whose subscription is anchored on January 31 tried to upgrade on
   February 10 and got a server error: `ValueError: day is out of range for month`.
