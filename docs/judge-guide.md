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

The payment action states that Paystack is unavailable. There is no fake test
payment and no synthetic MC or donor recording.
