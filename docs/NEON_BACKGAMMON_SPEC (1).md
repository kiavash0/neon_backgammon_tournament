# Neon Backgammon Tournament — Project Specification

**Version:** 1.0 (Draft)
**Date:** 2026-07-26
**Audience:** This document is written to be executed by a Claude model (Claude Code or similar) implementing the project phase by phase. Each phase has a Definition of Done. Do not skip phases. Write tests as you go.

---

## 1. Project Overview

**Neon Backgammon Tournament** is a free-to-enter, multiplayer backgammon tournament platform available on **Web, Android, and iOS**, all connecting to a single central game server.

Core loop:

1. User signs up / logs in (any platform).
2. User enters the **Lobby** and joins a tournament room of a chosen size: **2, 4, 8, 16, 32, 64, 128, 256, or 512 players**.
3. When a room fills, a **single-elimination tournament** starts automatically.
4. Players play backgammon matches; losers are eliminated; the last player standing is the champion.
5. Ads (interstitial / rewarded video) are shown around matches. Ad revenue attributed to the tournament forms the **prize pool**.
6. The champion receives a cash prize = **payout_rate × tournament ad revenue** (payout_rate configurable, default 50%). The prize amount is finalized only at the end of the tournament.
7. Winnings accumulate as account balance; users can withdraw via a payout provider once they reach a minimum threshold.

**Business model:** 100% ad-funded. Users never pay anything — no entry fees, no in-app purchases, no virtual currency for sale. Revenue = total ad impressions across the app; costs = prize payouts (a fixed fraction of tournament-attributed ad revenue) + infrastructure.

---

## 2. Legal & Compliance Constraints (MUST-FOLLOW — these shape the product design)

These constraints were established through prior research and are **non-negotiable design rules**:

1. **Entry must be completely free.** No entry fee, no purchase, no virtual-currency stake. This removes the "consideration" element of the gambling test (prize + chance + consideration), which is what keeps the product legally a free prize competition / sweepstakes-style promotion rather than gambling, in most jurisdictions (US majority rule, UK "free draw" concept).
2. **Never make watching an ad a REQUIRED condition of tournament entry.** Required ad-watching could be argued as "consideration" in some jurisdictions. Ads are shown automatically between/after matches (interstitials) and optionally (rewarded video for cosmetic perks), but the registration flow itself must be a free tap with no gated action.
3. **No purchasable virtual currency, ever.** Adding paid coins later would move the product into social-casino / dual-currency territory, which is under active regulatory attack. Do not build IAP for currency.
4. **No peer-to-peer transfer** of balance, credits, or any in-app item of value between users.
5. **Age gate 18+** at signup (date-of-birth entry + attestation; stricter verification at payout).
6. **Official Rules page** must exist in-app and on the web: eligibility (age, excluded countries), how winners are determined, prize calculation method, payout terms, sponsor identity. Required by app stores and prize-promotion law.
7. **Geo-eligibility list**: maintain a configurable allowlist/blocklist of countries. Launch conservatively (e.g., UK, Ireland, EU, US) and expand after legal review per region. Some US states have prize registration/bonding thresholds (FL/NY/RI, ~$5,000+) — irrelevant at cent-level prizes but must be monitored if prize pools grow.
8. **Tax/KYC at payout**: collect identity info only when cumulative payouts cross provider/legal thresholds (e.g., US 1099 territory at $600/yr). Design the ledger so cumulative annual payouts per user are queryable.
9. **App Store note:** even free-entry prize apps get scrutiny under Apple guideline 5.3 (gambling/contests). The app listing and in-app copy must clearly state: free entry, skill-based game, no purchase necessary, official rules link. Never use gambling language ("bet", "wager", "stake") anywhere in UI, store listing, or marketing.

---

## 3. High-Level Architecture

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│   Web UI    │  │  Android    │  │    iOS      │
│ (HTML/JS)   │  │             │  │             │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │  HTTPS (REST)  │  + WSS (WebSocket)
       └────────┬───────┴────────┬───────┘
                ▼                ▼
        ┌───────────────────────────────┐
        │        Game Server            │
        │  FastAPI + Uvicorn (Python)   │
        │                               │
        │  • Auth service (JWT)         │
        │  • Lobby / Room manager       │
        │  • Tournament manager         │
        │  • Backgammon engine          │
        │  • Real-time match gateway    │
        │  • Ad-revenue attribution     │
        │  • Wallet / ledger            │
        │  • Payout service (prod)      │
        └───────────────┬───────────────┘
                        ▼
        Demo:  .h5 file store (h5py)  ── swappable ──▶
        Prod:  PostgreSQL + Redis
```

**Key architectural rules:**

- **Server-authoritative everything.** Clients are dumb renderers + input devices. Dice are rolled on the server. Move legality is validated on the server. Clients never compute or report outcomes.
- **Storage behind a repository interface** (`StorageBackend` abstract class) so the demo `.h5` backend can be swapped for PostgreSQL without touching business logic.
  - *Implementation note:* HDF5 (`.h5` via `h5py`) is requested for the demo and should be implemented, but it is a poor fit for concurrent read/write of user records. Guard it with a single asyncio lock (acceptable for demo scale). Also implement a SQLite backend in the same phase (cheap to do behind the interface) and make backend selection a config flag — SQLite will make demo testing far less painful and is the recommended default for local dev.
- **Real-time layer:** WebSockets (`/ws`) for match play, lobby updates, and tournament bracket updates. REST for everything else (auth, profile, history, payout requests).
- **Single async event loop per process** for the demo (matches the user's prior architecture preference from the trading-bot design); horizontal scaling in production via multiple Uvicorn workers + Redis pub/sub for cross-process room/match state.

---

## 4. Backgammon Engine Specification

The engine must be a **pure, deterministic, fully-tested Python module** with no I/O and no knowledge of networking. Given (state, dice, move) it answers legality and produces the next state.

### 4.1 Board representation

- 24 points, plus **bar** and **borne-off** trays for each player.
- Suggested representation: `points: list[int]` of length 24 where positive = White checkers, negative = Black checkers; plus `bar_white, bar_black, off_white, off_black: int`.
- Standard starting position (per player): 2 on the 24-point, 5 on the 13-point, 3 on the 8-point, 5 on the 6-point.

### 4.2 Dice ("industry standard two dice throw")

- Two independent, uniform dice 1–6 per roll, generated **server-side** with a CSPRNG (`secrets.randbelow(6) + 1` — never `random.random`).
- **Doubles = four moves** of that value.
- **Opening roll:** each player rolls one die; higher goes first and plays the two dice shown; ties re-roll.
- **Provable fairness (production requirement, stub in demo):** per-game server seed; publish `SHA-256(server_seed)` at game start; derive all rolls from `HMAC(server_seed, game_id || roll_index)`; reveal `server_seed` at game end so players can verify the sequence. This directly addresses the #1 complaint in online backgammon ("rigged dice").
- Log every roll with timestamp and roll_index for audit.

### 4.3 Movement rules (must all be enforced server-side)

- Move checkers toward the player's home board; each die is a separate move (a checker may use both).
- A point with **2+ opposing checkers is blocked**.
- Landing on a single opposing checker (**blot**) hits it to the bar.
- A player with checkers **on the bar must enter them first** (into the opponent's home board); no other move is legal until all are entered.
- **Forced-move rules:** if both dice can be played, both must be played; if only one can be played, the higher must be played if possible; if no legal move exists, the turn is skipped (server auto-skips and notifies).
- **Bearing off** only when all 15 checkers are in the home board; exact rolls bear off from the matching point; higher rolls bear off from the highest occupied point; standard overshoot rules.
- Win = first player to bear off all 15 checkers.

### 4.4 Match format (v1 — keep it simple)

- **Single game per tournament match.** No doubling cube in v1 (adds significant rules + UI complexity; add later as "advanced tournaments"). Gammon/backgammon have no effect in single-elimination win/lose — record them in stats only.
- **Move timer:** default 30 seconds per turn + a 2-minute per-player reserve bank. Timer expiry ⇒ server plays a forced move if only one legal move exists, else forfeits the turn; 3 consecutive timeouts ⇒ match forfeit.
- **Disconnect handling:** 60-second reconnect grace (state preserved; timer paused up to once per player per game); failure to return ⇒ forfeit. Both-players-disconnected ⇒ pause up to 2 minutes, then double forfeit (opponent in next round gets a bye… but see §5.4 — in single elim a double forfeit advances a randomly selected player to keep the bracket sound; log the incident).

### 4.5 Engine API sketch

```python
class GameState:            # frozen dataclass, JSON-serializable
    ...
def initial_state() -> GameState
def roll_dice(rng) -> tuple[int, int]
def legal_moves(state, dice) -> list[MoveSequence]
def apply_move(state, move) -> GameState        # raises IllegalMove
def is_terminal(state) -> Winner | None
```

**Testing requirement:** ≥ 95% branch coverage on the engine. Include golden-position test vectors (bar entry, forced higher die, bear-off overshoot, no-legal-move skip, doubles with partial playability). The engine is the heart of trust in the product — a wrong legality ruling with money on the line is a reputation-ending bug.

---

## 5. Lobby, Rooms & Tournament Management

### 5.1 Room model

A **room** is a waiting container for one tournament of a fixed capacity.

| Capacity | Open rooms maintained in lobby | Replenish rule |
|---|---|---|
| 2, 4, 8 | **20 open rooms each** (config: `SMALL_ROOM_POOL=20`) | The moment a room fills (or shortly after — must be < 1s), spawn a replacement so the lobby always shows ~20 joinable rooms per small size. Small rooms fill fast; replenishment must be event-driven (on `room_filled`), not polled. |
| 16, 32, 64, 128, 256, 512 | **1 open room each** | On fill, immediately spawn the next room of that size. |

- Room lifecycle: `OPEN → FULL → TOURNAMENT_RUNNING → FINISHED` (or `CANCELLED`).
- Lobby WebSocket channel broadcasts room occupancy in real time (`room_update {room_id, size, joined, state}`) so users watch rooms fill live.
- A user may be registered in **at most one room/tournament at a time** (v1 rule; prevents self-play collisions and simplifies UX).
- **Fill-timeout for large rooms:** a 512 room may take days to fill at low DAU. Config `ROOM_FILL_TIMEOUT` (e.g., 24h for ≥128). On timeout: notify registrants and either (a) cancel + release players, or (b) **downgrade**: if ≥ next-lower power of 2 players are present, start at that size with the earliest joiners, release the rest. Downgrade is the better UX; make it the default, clearly disclosed in Official Rules.
- **Anti self-play:** one account per device per room enforcement (see §10 fraud section) — especially critical for 2-player rooms where a user with 2 accounts wins 100% of the time.

### 5.2 Tournament engine

- Single elimination, capacity ∈ {2,…,512}; total matches = n − 1.
- On `room_filled`: freeze roster, **random seeding** (CSPRNG shuffle), generate bracket, persist, notify all players (push + WS), start round 1 after a 30-second "get ready" countdown.
- Rounds run in parallel within themselves; a round starts when the previous round fully resolves. Players get a round-start notification and `MATCH_JOIN_TIMEOUT` (default 90s) to appear, else forfeit.
- Bracket state is broadcast on the tournament WS channel after every match result (spectatable bracket view).
- Many tournaments run concurrently; the tournament manager must be stateless-per-tournament (all state in storage/Redis) so any worker can advance any tournament — this is the key to horizontal scaling and crash recovery.
- **Crash recovery requirement:** on server restart, all `TOURNAMENT_RUNNING` tournaments must resume from persisted state (matches in progress may be restarted from the last persisted game state; persist game state after every applied move).

### 5.3 Prize pool mechanics

- Every ad impression is logged: `ad_impression {user_id, tournament_id | null, match_id | null, network, format, est_revenue_usd, ts}`.
- **Attribution rule:** impressions shown on screens belonging to a tournament context (post-match interstitial, between-round bracket screen) carry that `tournament_id`. Lobby/menu impressions have `tournament_id = null` (general revenue, not in any pool).
- Tournament prize pool = `payout_rate × Σ est_revenue_usd` of attributed impressions. `payout_rate` is config, default **0.50**; changeable per tournament type; must be stated in Official Rules ("winner receives at least X% of tournament ad revenue").
- **Revenue estimation reality:** ad networks do not report exact per-impression revenue instantly. Use **AdMob Impression-Level Ad Revenue (ILRD / paid events)** which provides an *estimated* value per impression in near-real time — good enough to compute the pool at tournament end. Where ILRD is unavailable (web), use a per-country eCPM lookup table (config, updated monthly from network reports). Display prizes as "estimated" until a monthly reconciliation job trues up estimates vs. actual network payments; the ledger supports adjustment entries. **Never promise an exact prize before tournament end** — UI shows a live "current estimated prize pool" ticker (great engagement mechanic: the pot visibly grows as the tournament runs).
- Worked examples (from product owner):
  - 2-player tournament, 2 impressions @ $0.015 ⇒ pool $0.03 ⇒ winner $0.015 at 50%.
  - 32-player tournament, total ad revenue $1.00 ⇒ winner $0.50.
- On tournament finish: credit winner's wallet ledger with `prize_credit {tournament_id, amount_usd, estimated: true}`; mark reconciled after monthly true-up.
- **Consider (v2, config-gated):** small runner-up share (e.g., winner 40%, finalist 10%) — better retention than winner-take-all for large brackets. Ship v1 winner-take-all as specified.

### 5.4 Edge cases the implementation MUST handle

- Player in a running tournament logs in from a second device ⇒ transfer the session (kick old socket), never duplicate.
- Double forfeit in a match ⇒ advance one player chosen by CSPRNG; log incident; if it's the final, the coin-flip winner takes the prize (disclose in rules).
- Tournament with zero attributed ad revenue (all ad fills failed) ⇒ prize = $0; UI must handle gracefully ("prize pool: $0.00 — ad delivery failed"); log alert (this indicates an ads integration problem).
- User deletes account mid-tournament ⇒ treat as forfeit of remaining matches; unpaid balance handled per §7 (payout or escheat per ToS).

---

## 6. Server Application Specification

### 6.1 Tech stack (demo → production)

| Concern | Demo (Phase A) | Production (Phase B) |
|---|---|---|
| Language / framework | Python 3.12, FastAPI, Uvicorn | Same, behind Nginx/Caddy (TLS) + multiple workers |
| Storage | `.h5` via h5py (+ SQLite alt backend), single-process | PostgreSQL 16 (SQLAlchemy + Alembic migrations) |
| Real-time state / pub-sub | in-process dicts | Redis (rooms, presence, cross-worker pub/sub, rate limits) |
| Auth | JWT access (15 min) + refresh (30 d), argon2id password hashing | Same + email verification, optional TOTP, OAuth (Google/Apple sign-in — required by Apple if any 3rd-party login is offered) |
| Deployment | `uvicorn app:app --reload` local | Docker + docker-compose (or ECS/Cloud Run later), CI/CD via GitHub Actions |
| Observability | stdlib logging | Structured JSON logs, Prometheus metrics, Grafana, Sentry |

### 6.2 REST API sketch

```
POST /auth/signup            {email, password, display_name, dob, country}
POST /auth/login             → {access, refresh}
POST /auth/refresh
GET  /me                     profile, balance, stats
GET  /lobby                  open rooms snapshot (WS for live updates)
POST /rooms/{id}/join        (idempotent; 409 if already in a room)
POST /rooms/{id}/leave       (only while room OPEN)
GET  /tournaments/{id}       bracket, status, estimated prize pool
GET  /tournaments/{id}/matches/{mid}
GET  /history                my tournaments & matches
POST /payout/request         (prod only) {amount, method}
GET  /rules                  official rules (also public web page)
POST /ads/ssv-callback       server-side ad verification webhook (prod)
```

### 6.3 WebSocket protocol (single `/ws` endpoint, JWT-authenticated, JSON messages)

Client→Server: `subscribe_lobby`, `subscribe_tournament {tid}`, `match_ready {mid}`, `move {mid, seq}`, `resign {mid}`, `ping`.
Server→Client: `room_update`, `tournament_start`, `bracket_update`, `match_start {mid, opponent, your_color}`, `dice {roll_index, d1, d2}`, `state {game_state, legal_moves}`, `opponent_move`, `timer {remaining}`, `match_result`, `tournament_result {winner, prize_usd_est}`, `error {code, msg}`.

Server sends `legal_moves` with every state so clients never compute rules (thin clients, no rules drift across 3 platforms).

### 6.4 Robustness & scale target

- Target: **1,000+ concurrent users**, which is trivially within one async Uvicorn process for turn-based traffic (~a few hundred msgs/sec), but design for horizontal scale anyway (stateless workers + Redis) because ad-funded economics only work at much larger scale.
- Backpressure: per-connection send queues with drop-oldest for lobby broadcasts; never drop match messages.
- Rate limiting: per-IP on auth endpoints (protect against credential stuffing), per-user on WS message rate (move spam).
- Idempotency keys on join/payout endpoints.
- Load testing gate before launch: see §12.

---

## 7. Payments (User Payouts) — RESEARCH REQUIRED, design constraints below

We receive **no money from users**, so no inbound payment processing exists. We only need **outbound micro-payouts** to winners worldwide. This is genuinely hard at cent-scale; the design must absorb that reality.

### 7.1 Non-negotiable design decisions

- **Wallet + ledger model:** winnings accrue to an in-app USD balance (append-only double-entry ledger: `credit(prize)`, `debit(payout)`, `adjustment(reconciliation)`). Users cash out on demand **above a minimum threshold**. This is the industry-standard answer to "how do we pay $0.0075 without fees eating it": you don't — you accumulate.
- **Minimum payout threshold:** config, suggested **$5.00** initially (mirrors AdSense-style thresholds users already understand). Below threshold, balance just accumulates. Threshold and any fee pass-through must be in Official Rules and shown before withdrawal.
- **The balance is a payable liability, not a plaything:** no spending it in-app, no transferring it, no converting it to anything. It exists only to be withdrawn. (Keeps us out of e-money/stored-value regulatory territory — verify with counsel.)
- **KYC gate at first payout** (name + country + payout account), heavier verification at provider-required thresholds. Store cumulative annual payout per user for tax reporting (US 1099 threshold, etc.).
- Payout flow: user clicks Withdraw → server validates balance/threshold/KYC → creates `payout_request (PENDING)` → calls provider API → webhook confirms → ledger `debit` + status `PAID`. Automatic, no manual step, but with a fraud-review hold queue (§10) for flagged accounts.

### 7.2 Provider candidates to research (Phase B task — verify current fees/coverage before choosing)

| Option | Notes to verify |
|---|---|
| **PayPal Payouts / Masspay API** | Widest consumer reach; per-payout fees historically ~2% capped for international, flat cents domestically; recipient needs PayPal. Strong candidate for v1. |
| **Wise API** | Good FX/low fees for bank transfers; per-transfer fee makes micro-payouts viable only above ~$5–10. |
| **Tremendous / Runa** | Payout-as-a-service: recipients choose PayPal / bank / gift cards; often **zero fee to sender for gift-card redemption** — gift cards may be the cheapest rail for small amounts and are legally clean prizes. Strong candidate. |
| **Stripe Connect (transfers to Express accounts)** | Powerful but onboarding friction is heavy for casual winners. Probably not v1. |
| Crypto/stablecoins | Cheap rails but adds regulatory + UX burden; **avoid for v1**, revisit only with legal advice. |

Research deliverable: a comparison doc (fees at $5/$20/$100 payout sizes, country coverage incl. UK/IE/EU, API quality, KYC handled by provider vs us, payout speed) → pick primary + fallback provider. **Recommendation to validate: Tremendous (gift-card default, PayPal option) as v1 primary, PayPal Payouts as fallback.**

### 7.3 Demo behavior

Phase A skips all of this: winners receive **virtual credit** in the ledger (same schema, `provider = "demo"`), visible in profile. The ledger built in the demo is the production ledger — only the payout executor is stubbed.

---

## 8. Ads Integration & Anti-Skip (Production Phase)

### 8.1 Networks

- **Android / iOS:** Google AdMob (interstitial + rewarded). Enable **ILRD (impression-level ad revenue / paid events)** for per-impression revenue attribution (§5.3). Add mediation (AppLovin MAX or AdMob mediation) later for eCPM lift; v1 = AdMob alone for simplicity.
- **Web:** Google AdSense / Ad Placement API (H5 games) for interstitial & rewarded on web; revenue attribution via country-eCPM table (web lacks ILRD).
- Consent: implement GDPR/UK **UMP consent flow** (required for EU/UK users; affects eCPM); ATT prompt on iOS.

### 8.2 Placement map (v1)

| Placement | Format | Tournament-attributed? |
|---|---|---|
| After each match (both players) | Interstitial | ✅ |
| Between rounds (bracket screen) | Interstitial ≤1/round | ✅ |
| Lobby banner | Banner | ❌ (general revenue) |
| Optional "watch ad" for cosmetics (board themes) | Rewarded | ❌ — **never gate entry/prizes on it** (legal §2.2) |

### 8.3 Anti-skip / ad integrity (this protects the prize pool from fraud)

- **Rewarded ads:** use **AdMob Server-Side Verification (SSV)** — network calls our `/ads/ssv-callback` with a signed payload; only SSV-confirmed impressions earn revenue attribution. Client claims are never trusted.
- **Interstitials:** client fires `ad_shown` events but the server only *counts* impressions that also appear in ILRD paid events (mobile). Mismatch beyond tolerance ⇒ flag account (modded APK signal).
- **Client hardening:** Google **Play Integrity API** (Android) and **App Attest / DeviceCheck** (iOS) attestation on login and before payout — this is the main defense against modded clients that strip ads. Fail attestation ⇒ can play, cannot accrue prize/payout (soft-fail with appeal path).
- **Web reality check:** ad blockers cannot be reliably defeated. Policy: detect blocked ad delivery and show a polite screen — users with blockers can play **casual (non-prize) matches** but not prize tournaments ("prize pools are funded by ads"). This is a fairness rule, not consideration (they still never pay).
- All impression logs are append-only with device/IP fingerprint for fraud analytics (§10).

---

## 9. Hosting & Infrastructure (decide in Phase B; requirements below)

- Demo runs locally. Production candidates: **Hetzner/OVH VPS** (best price/perf for an EU-centric start, ~€10–20/mo covers thousands of concurrent turn-based users), **AWS Lightsail/ECS**, **GCP Cloud Run + Cloud SQL**. Decision criteria: cost at 1k concurrents, EU data residency (GDPR — user base starts UK/IE/EU), managed Postgres availability, WebSocket support (Cloud Run WS timeouts — verify), egress pricing.
- Non-negotiables regardless of host: TLS everywhere (Caddy/Let's Encrypt), daily automated Postgres backups + point-in-time recovery, secrets in env/secret-manager (never in repo), separate staging environment, infra as code (docker-compose v1 → Terraform if moving to AWS/GCP).
- GDPR: privacy policy, data-processing records, user data export & delete endpoints (also an Apple/Google store requirement), EU hosting region preferred.

---

## 10. Security & Anti-Fraud (CRITICAL — free entry + real payouts = magnet for abuse)

**Threat #1 is not hacking; it's multi-accounting and bot farming.** A scripter with 2 accounts joining the same 2-player room wins 100% of prizes; a bot farm harvesting micro-prizes at scale destroys the economics.

Mandatory mitigations:

1. **One human = one account:** email verification (v1) + phone verification before first payout (prod); device fingerprinting; Play Integrity / App Attest (§8.3).
2. **Same-device / same-IP collision rules:** two accounts from one device/IP-subnet may not be seated in the same room (especially sizes 2/4/8). Seating algorithm enforces separation; violations flagged.
   - **Environment-gated, NOT hardcoded.** Implement this as `FRAUD_SEATING_CHECK: enabled | disabled | log_only`, read from server config/env var — never a hardcoded `if` that has to be commented out to test.
     - `enabled` — production default. Same device fingerprint or same IP/subnet cannot be seated together; violation blocks seating and is logged.
     - `log_only` — recommended for **staging and internal QA**: the check runs and logs what *would* have been blocked, but does not actually block seating. This lets the team verify the detection logic is correctly identifying collisions before it's ever allowed to affect real matchmaking.
     - `disabled` — for **local dev and automated load/integration testing only** (Phase A dev loop, and the k6/Locust/scripted-client tests in §12, which by their nature run every fake client from one machine/IP). Must default to this in local `.env.example` / docker-compose dev config.
   - **Hard safety rail so this can never leak into production by accident:** the server must refuse to start with `FRAUD_SEATING_CHECK=disabled` (or `log_only`) if `ENV=production`, and refuse to start with real payout provider credentials configured unless `FRAUD_SEATING_CHECK=enabled`. This ties the fraud check directly to the presence of real money — you cannot go live with real payouts and the check off, even by mistake.
   - This same env-gated pattern applies to attestation checks (Play Integrity / App Attest, §8.3) and the ad SSV requirement — all fraud/anti-abuse gates should be toggleable for testing but hard-locked on whenever the payout provider is live.
   - Add a line item to the Phase A9 and Phase B8 Definitions of Done: "confirm fraud gates are `enabled` in staging before load test sign-off, and confirm the production-boot refusal rule actually fires in a test (start server with `ENV=production` + `FRAUD_SEATING_CHECK=disabled` and assert it fails to boot)."
3. **Payout review queue:** automatic holds on anomalies — win-rate outliers in small rooms, accounts that only play 2-player rooms against fresh accounts, impression/ILRD mismatches, many accounts → one payout destination.
4. **Collusion/dumping detection:** log all match data; flag improbable move-quality drops (v2: score moves against a backgammon evaluation engine like GNU Backgammon's, and flag deliberate losing).
5. **Standard app security:** argon2id password hashing, JWT with short expiry + refresh rotation, rate limiting, parameterized queries only, strict Pydantic input validation on every endpoint & WS message, CORS locked to our origins, security headers, dependency audit (pip-audit) in CI, no PII in logs.
6. **Server-authoritative game integrity:** dice server-side CSPRNG (§4.2), moves validated server-side, provably-fair seed scheme published.
7. Secrets & payout provider keys in a secret manager; payout executor runs with least privilege; 4-eyes (manual approval) over a daily aggregate payout cap initially (e.g., >$50/day total triggers manual release).

---

## 11. Client Applications

Build order (per product owner): **Web → Android → iOS.**

- **Phase A Web:** plain HTML/CSS/JS (or lightweight Vue/React via CDN — implementer's choice, keep the build simple), talking REST + WS. Screens: auth, lobby (live room grid), bracket view (live), match board (drag-or-tap checker movement, dice display, move timer, legal-move highlighting from server data), profile/balance/history, official rules. Provided **neon-styled art assets** will be supplied for boards/checkers/dice/UI chrome; build the demo with placeholder assets structured so final assets drop in (asset manifest + theme file).
- **Phase B Android/iOS decision point:** strongly consider **one cross-platform codebase (Flutter or React Native)** instead of two native apps — for a solo/small team, two native clients triple maintenance for a board game that needs no native-heavy features. AdMob, Play Integrity/App Attest, and WS all work fine in Flutter/RN. Document the decision; default recommendation: **Flutter** (single codebase → Android, iOS, and can even replace web later).
- Mobile extras: push notifications (FCM/APNs) for "your round starts", "tournament filled", "you won $X"; reconnect-friendly WS layer; offline = graceful error, never fake play.
- **App store readiness checklist:** 18+ rating, contest/official-rules links in listing, privacy nutrition labels / Data Safety form, account-deletion in app (both stores require), no gambling terminology, screenshots showing free entry. Expect Apple review friction on prize mechanics — prepare a review note explaining free entry + skill game + official rules (guideline 5.3 defense).

---

## 12. Testing, Load & Launch Gates

- **Unit:** engine ≥95% branch coverage (§4.5); tournament bracket logic; prize-pool math incl. reconciliation adjustments; ledger invariants (sum of entries per user == balance; ledger never negative).
- **Integration:** full tournament simulation tests — spin up server, script N fake WS clients playing random-legal-move games through 2/8/32-size tournaments, assert bracket integrity, prize credit, crash-recovery (kill server mid-round, restart, tournament completes).
- **Load (pre-launch gate):** k6 or Locust: 1,000 concurrent WS clients across ~50 parallel tournaments, p95 move-ack < 300ms, zero dropped match messages, 24h soak without memory growth. Run against staging on production-equivalent hardware. Since all simulated clients originate from the same load-testing machine/IP, run this with `FRAUD_SEATING_CHECK=disabled` (§10.2) — but immediately follow it with the `log_only` staging pass (real testers, real varied devices/IPs where possible) to confirm the fraud gate itself behaves correctly before it's ever flipped to `enabled` in production.
- **Security gate:** pip-audit clean, auth fuzzing, at minimum an automated OWASP ZAP pass; payout flow pen-tested before real money moves.
- **Store launch:** closed beta (Play internal testing / TestFlight) with virtual-credit prizes → limited-country launch with tiny prize pools → scale.

---

## 13. Marketing & Growth (later phase, capture ideas now)

- Positioning: "Free backgammon tournaments. Real prizes. Zero cost, ever." — the free-entry + cash-prize combo is the hook; the live-growing prize pool is the retention mechanic.
- Channels: backgammon communities (r/backgammon, BG forums, Heroes/Galaxy player communities), ASO around "free backgammon tournament", short-form video of final matches, referral program (**cosmetics/badges as referral rewards, never balance transfers** — §2.4).
- Retention: daily scheduled "featured" tournaments at fixed times, leaderboards/ELO, streaks with cosmetic rewards, spectate mode for finals.
- KPI economics to watch from day 1: eCPM by country, impressions/user/day, prize payout ratio, cost-per-install vs LTV(ad revenue) — the whole business is `ad_revenue_per_user > payout_share + infra`.

---

## 14. Implementation Roadmap (execute in order; each phase gated by its DoD)

### PHASE A — Demo / Model (local, virtual credits, no ads, no payments)

**A1. Repo & scaffolding** — mono-repo (`/server`, `/web`, `/mobile`, `/docs`), Python 3.12, FastAPI, pytest, ruff, pre-commit, docker-compose (server + future postgres/redis stubs). *DoD: `make dev` runs an empty FastAPI app; CI runs tests+lint.*

**A2. Backgammon engine** — pure module per §4 + full test suite. *DoD: coverage gate passes; CLI script plays a random-legal self-play game to completion.*

**A3. Storage layer** — `StorageBackend` interface; h5py backend + SQLite backend; entities: users, rooms, tournaments, matches, games(move log), ledger, ad_impressions(stub). *DoD: backend swappable by env var; CRUD tests pass on both.*

**A4. Auth + profiles** — signup/login/refresh, argon2id, JWT, /me. *DoD: auth flow tested incl. bad-credential lockout.*

**A5. Lobby & rooms** — room pools per §5.1 (20×{2,4,8}, 1×{16..512}), auto-replenish, join/leave, lobby WS broadcasts. *DoD: scripted clients fill a room; replacement room appears <1s; occupancy broadcast live.*

**A6. Match play over WS** — matchmaking within bracket, server dice, server legality, timers, reconnect grace, forfeit rules. *DoD: two browser tabs play a full legal game; disconnect/reconnect works.*

**A7. Tournament manager** — bracket generation, round advancement, crash recovery, virtual-credit prize using a **stub revenue model** ($0.015/simulated-impression so the prize math path is real). *DoD: scripted 8-player tournament completes end-to-end; winner's ledger credited; server kill/restart mid-tournament recovers.*

**A8. Web UI (demo)** — screens per §11 with placeholder neon assets. *DoD: a human can sign up, join a 2-room, play, win, and see credited balance — the full demo loop.*

**A9. Demo review checkpoint** — demo video + retro doc; decide go/no-go and Flutter-vs-native for mobile.

### PHASE B — Production

**B1.** PostgreSQL migration (Alembic), Redis integration, multi-worker.
**B2.** Hosting decision + staging env + CI/CD + TLS + backups (§9).
**B3.** Ads integration + consent + ILRD attribution + SSV (§8).
**B4.** Anti-fraud stack: attestation, device rules, review queue (§10).
**B5.** Payout provider research → integration + KYC + thresholds (§7).
**B6.** Legal pack: Official Rules, ToS, Privacy Policy, geo-eligibility config (counsel review — budget for a 1–2h consult minimum).
**B7.** Mobile app(s) (§11), push notifications.
**B8.** Load + security gates (§12).
**B9.** Store submissions + closed beta → limited launch → scale (§12, §13).

### Instructions to the implementing model

1. Work strictly phase by phase; do not start a phase before the previous DoD is demonstrably met (show test output).
2. Keep the engine pure and the storage swappable — these two boundaries are the architecture.
3. Every money-touching path (ledger, prize credit, payout) gets tests before code is considered done, and the ledger is append-only from day 1.
4. When this spec conflicts with a legal constraint in §2, §2 wins; stop and flag rather than improvise.
5. Maintain `/docs/DECISIONS.md` (ADR log) — every deviation from this spec gets an entry with reasoning.

---

## 15. Open Questions (park here; resolve at the marked phase)

1. Payout provider choice & real fee table — **B5**.
2. Flutter vs native mobile — **A9**.
3. Doubling cube / match-to-N-points "advanced" tournaments — post-launch.
4. Runner-up prize split for large brackets — post-launch A/B.
5. Hosting vendor — **B2**.
6. Regional launch list & counsel sign-off — **B6**.
7. ELO/rating system & skill-banded rooms — post-launch (helps retention; also dilutes shark-vs-newbie problem).
8. Name/branding check: trademark search for "Neon Backgammon Tournament" before store submission — **B9**.
