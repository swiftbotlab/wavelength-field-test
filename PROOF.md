Ref: KB-2410-09

# Proof of a working Wavelength mainnet account

Captured 2026-10-27 12:54 UTC from our own daemon with `wavecli --json`. The identity key (mailbox ID) is shortened; nothing secret is shown.

## `wavecli getinfo`
```json
{
  "version": "0.2.0",
  "commit": "b82bd54",
  "network": "mainnet",
  "block_height": 973400,
  "server_connected": true,
  "wallet_type": "lwwallet",
  "wallet_state": "WALLET_STATE_READY"
}
```
identity_pubkey: `03bdb9ea...d359bb1e` (the value submitted with the mainnet access request on 2026-10-27).

Server limits reported by `getinfo`: max_user_balance 300,000 sats, max_vtxo_amount 50,000 sats, min_boarding_amount 1,000 sats, min_operator_fee 1,000 sats, boarding min_confirmations 6.

## Funding (public chain data)
- BTC deposit to our boarding address: tx `44803060c283e5a1f5f2d48b897f32ac96b782e6ad8721f9cba48db2196fee1f` (10,553 sats, block 973383).
- Boarded in the server round that completed 2026-10-27 12:02:21 UTC (commitment tx `1183336db951599630b5d169d771273c268b6903d02bc5fc1bdfe0855f804e9c`, block 973392).

## Wallet ledger (`wavecli activity`)
| kind | status | amount (sats) | fee field | counterparty |
|---|---|---|---|---|
| EXIT | PENDING | -9298 | 0 | 32Jcu66LAonGfFqnJoH4srozgZpGQAyx |
| RECV | COMPLETE | 1000 | 0 |  |
| SEND | COMPLETE | -1000 | 0 |  |
| SEND | COMPLETE | -2 | 0 | credit |
| SEND | COMPLETE | -100 | 0 | credit |
| SEND | COMPLETE | -5 | 0 | credit |
| SEND | COMPLETE | -1000 | 0 |  |
| SEND | COMPLETE | -2 | 0 | credit |
| DEPOSIT | COMPLETE | 10553 | 0 | boarding |
| RECV | FAILED | 5000 | 0 |  |

Reading the ledger from the bottom: the 5,000-sat RECV is a limit-test invoice nobody paid (it expired); DEPOSIT is the boarding; the first -1,000 SEND moved sats into server credit; the -2/-5/-100 SENDs are the paid L402 calls (settled from credit); the second -1,000 SEND paid our second wallet's invoice in-Ark and the +1,000 RECV is that wallet paying it back; EXIT is the cooperative leave.

## Balance now (`wavecli balance`)
```json
{
  "confirmed_sat": "0",
  "pending_in_sat": "0",
  "pending_out_sat": "9298",
  "credit_available_sat": "886",
  "credit_reserved_sat": "0"
}
```
The remaining sats were sent back on-chain with a cooperative leave (the EXIT row) after the test; the server credit stays with the operator for later calls.
