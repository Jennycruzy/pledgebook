# Judge guide — current local build

The public link and HTTPS deployment are not ready yet. To try the current
local slice:

1. Put the AssemblyAI key in the local `.env` file.
2. Run `python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.
3. Open the page, choose **Start my demo launching**, and press **Start
   listening**.
4. Read a line from the invented script in a real human voice, or choose
   **Play a real WAV recording**.
5. Open **Needs checking** to play the exact evidence clip and resolve a flag.
6. Open **Register** to see the live words, recheck words, state, and CSV
   export.
7. Add a guest with follow-up consent, open **Follow-up**, and start the
   clearly disclosed assistant. A wrong-person answer never shares the amount.
8. For a payment demonstration, add the guest's email, answer the identity
   question as the right person, open the Paystack Test Mode link, and use the
   published test card `4084 0840 8408 4081` with any future expiry and CVV
   `408`. Return to Pledgebook and press **Check payment**. A successful
   verification changes the pledge to **Redeemed**.

The payment link is a real Paystack Test Mode checkout. No real money moves,
and there is no synthetic MC or donor recording.
