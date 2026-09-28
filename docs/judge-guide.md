# Judge guide — public demo

Open **https://pledgebook.54-154-121-30.sslip.io/** in a signed-out browser.
The page creates a private demo event for that visitor. Names and amounts are
invented, AssemblyAI processes the real voice, and Paystack is Test Mode only.

Try the path:

1. Choose **Start my demo launching**.
2. Open **Guest list**, add yourself, and tick follow-up consent if you want
   the call. Your name is inserted into the MC script.
3. Press **Start listening** and read the script in your own voice. If a
   microphone is unavailable, choose **Play sample recording**.
4. Open **Needs checking** to play the evidence clip and choose a guest,
   create a walk-in, mark anonymous, fix an amount, or reject the line. The QR
   link opens the usher view on a phone.
5. Open **Register** to see the live words, recheck words, state, and CSV
   export.
6. Open **Follow-up** and choose **Call about this**. The disclosed assistant
   checks identity before mentioning the amount.
7. After identity is confirmed, open the private pledge page. It plays the
   exact trimmed moment when safe; if neighbouring speech cannot be separated,
   it shows the words instead. Continue to Paystack Test Mode.
8. Use the published test card `4084 0840 8408 4081` with any future expiry and
   CVV `408`. Return to Pledgebook and press **Check payment**. A successful
   verification changes the pledge to **Redeemed**.

For local development:

1. Put the AssemblyAI key in the local `.env` file.
2. Run `python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.
3. Open `http://127.0.0.1:8000` and use the same path.

The payment link is a real Paystack Test Mode checkout. No real money moves,
and there is no synthetic MC or donor recording. The clearly disclosed
assistant may use AssemblyAI generated speech.
