Ref: KB-2410-09

# wavelength-field-test

Raw logs and driver scripts from a first-hand field test: an agent paying for APIs over Lightning with **Wavelength v0.2.0 on Bitcoin mainnet** (L402), compared with **x402** (USDC on Base) on the same kind of call. Run on 2026-10-27/28 UTC by Swift Bot Labs.

Full write-up: https://dev.to/swiftbotlab/ref-kb-2410-09-an-agent-paid-real-apis-over-lightning-wavelength-mainnet-vs-x402-on-base-5hfl Proof of the working mainnet account: [PROOF.md](PROOF.md).

## What is here

| path | what |
|---|---|
| `l402_run.py` | headless L402 driver: GET -> 402 -> decode the BOLT-11 amount locally -> `wavecli send` -> retry with `Authorization: L402 <macaroon>:<preimage>`; per-call and per-session sat caps; logs every step |
| `recv_test.py` | receive-side test between two of our own Wavelength wallets (invoice -> pay -> wait until the receiver can spend) |
| `x402_run.py` | x402 v2 payer for the same kind of call: reads `accepts`, signs one EIP-3009 `TransferWithAuthorization` locally, retries with `PAYMENT-SIGNATURE` |
| `results/l402_results.csv` | one row per step (challenge / pay / retry / token reuse): price, fee, rail, timings, result |
| `results/x402_results.csv` | one row per paid call with the Base tx hash |
| `results/limits/` | exact JSON errors from `wavecli` for the limit tests (receive above caps, sub-1,000-sat invoices, expired invoice) |

Macaroons, invoices and preimages are cut to short prefixes in the public logs. Nothing here holds a key, seed or password.

## Reproduce
1. Install Wavelength v0.2.0 from github.com/lightninglabs/wavelength/releases (check the manifest SHA-256 and the release signatures), create a wallet, request mainnet access with your `identity_pubkey`.
2. Start `waved` on mainnet (flags in the report), fund the wallet, unlock it.
3. `python3 l402_run.py probe` (pays nothing), then `python3 l402_run.py run --go`.
4. For x402: a Base wallet holding a little USDC; `x402_run.py probe`, then `x402_run.py run 5 --go` (the script derives its key from a local secrets file; adapt `account()` to your own key handling).

## License
MIT for the scripts. The logs are our own measurements.
