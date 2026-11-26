# Riftdogs roadmap

Riftdogs is a living galaxy you trade in. This roadmap shows the order we're building it in, what each release contains, and what has to be true before the next one starts. It replaces the 0.4-era roadmap; every feature requested there is placed in a phase below.

The order is deliberate. **The first goal is getting as many people as possible playing for free.** Each later phase depends on the one before it: there's no piracy loot or insurance until every credit and tonne of cargo is properly accounted for, and no lending, clans or asset sales until money can't be faked. Real money comes last, if at all.

Releases have overtaken the original version numbers: 0.13 to 0.15 went to Herbert, the new cockpit and the Trade Dog Licence, so phases no longer have version targets. Each phase has a GitHub milestone with the same name. Offline play stays available throughout.

Status as of 2026-11-26 (latest release 0.15.0):

| Phase | Theme | Status | Shipped so far |
| --- | --- | --- | --- |
| 1 | Open the doors | Done | 0.10: signed updates, server checks (enforcing), sealed saves, payment codes, invites; minimum client 0.11.0 |
| 2 | First flight | Under way | Herbert (0.13, 0.14), two-port stations with Y guidance (0.14), the Trade Dog Licence and check flight (0.15). Still to come: route planner, help from the key bindings, first contracts |
| 3 | Wider galaxy | Under way | riftdogs.com and the Riftdogs brand, every copy checking in (0.12). Next: a waitlist-only website with tester questions and referrals, an in-game waitlist that gates all play until a pilot is admitted, and an operator dashboard. Still to come: Windows, lifting the 8-pilot limit, wider invites, sound |
| 4 | The ledger | Planned | |
| 5 | Lawless space | Planned | Groundwork: ship numbers, channel 16 and Mayday calls (0.11) |
| 6 | Credit and crews | Planned | |
| 7 | Life on the lanes | Planned | |
| 8 | The frontier | Planned | The licence is the pilot's way out of the 8 core systems once the frontier exists |
| 9 | Owners and exchange | Ideas | |

---

## Phase 1 — Open the doors

**Goal:** make the shared galaxy safe to open to strangers.

- Signed updates: games install only releases signed with the Riftdogs release key, and never an older version.
- The server checks the economy: market trades only where you're docked, selling only what you hold, rate limits, and a money check on every uploaded save.
- Offline saves carry a seal, so edited saves are recognised.
- Payment codes: send credits to another player with a one-time code (1% fee; refunded if unclaimed after 7 days).
- Accounts: single-use invites, token rotation, account deletion, privacy notice and terms.
- Nightly server backups, off-site copies and health alerts.
- The game is renamed Riftdogs. Ticker stories open in their own window.

**Rollout:**
1. Server deployed. *(Done, 2026-11-21.)*
2. Release key created and pinned; 0.10.0 signed and published. *(Done.)*
3. A trial week, watching that no honest player is wrongly refused. *(Done.)*
4. 0.10.0 becomes the minimum version. Payment codes open. *(Done.)*
5. Players install and update from `womb4t/riftdogs`. *(Done.)*

**Done when:** the trial week has passed with no honest player refused, and every known player is on 0.10.

## Phase 2 — First flight

**Goal:** a new player can learn to fly, dock, trade and fight without reading anything.

- **Herbert**, an old hauler, takes new pilots through their first flights: landing, a second assisted landing, navigation, money and combat. Pilots choose their own destinations and trades while he teaches.
- Two docking bays with an approach corridor, lead-in and sector lights, glide-slope lights and ILS-style needles.
- A gentler first death for newcomers.
- A route planner.
- In-game help generated from the real key bindings, so it never goes out of date.
- First contracts: a few robust delivery and courier jobs rather than a long quest chain.

**Done when:** a first-time tester gets from the start screen to their first profitable trade unaided, and first-hour drop-off is measured.

## Phase 3 — Wider galaxy

**Goal:** more players, on more machines.

- A Windows build and installer.
- **A double-click Mac installer** (parked 2026-11-26): a `.dmg` download from riftdogs.com instead of the one-line Terminal install. It needs an Apple Developer ID ($99 a year) to sign and notarise the app; without one, macOS blocks downloaded apps with an "Apple cannot check it" warning. Worth it once enough Mac players are put off by the Terminal step.
- An itch.io page and the Riftdogs website, with the brand rolled out.
- The 8-pilot limit lifted; presence and the shared market tested at higher numbers.
- Invites opened up more widely.
- Original sound cues for targeting, threats, docking and travel, with volume and mute controls.

**Done when:** Windows players can install, update and play, and the server holds a load test well above the old limit.

## Phase 4 — The ledger

**Goal:** every credit and every tonne has a traceable history held by the server. The phases after this are built on it.

- A server-held wallet with double-entry accounts: money moves between accounts and is never simply created.
- Every trade and payment gets a unique number from the server. A resent request is recognised and never applied twice.
- Signed, time-stamped numbers issued in advance for offline play, so offline trades can be counted and put in order when the game reconnects.
- Cargo is held in loads with their own signed IDs. Loads split and merge, and the server keeps each load's history: bought, mined, salvaged, rewarded, sold, seized.
- An append-only log where each record is linked to the one before it, so any tampering with history shows. This takes the useful part of a blockchain without its cost: the server stays the single authority.
- Stable IDs and save migrations for ships, modules and cargo, so later phases don't break old saves.

**Done when:** every player's books balance exactly, and credits or cargo with no history can't be held.

## Phase 5 — Lawless space

**Goal:** a piracy career, player-versus-player combat, and the law that answers it.

- Piracy career, PvP, and shared wrecks and cargo canisters between players.
- Distress calls that other players can see and answer.
- **Orbit Wardens:** fuller police rules, security levels by system, self-defence and reputation. A clean trader defending against pirates isn't treated as a criminal. Safer space carries a trading tax, so profit follows risk.
- Police bounties on wanted pilots; bounty work for players.
- Ship insurance from Halcyon Mutual ("Back in the black."): an annual premium of 5% covers the ship and fitted gear, not cargo or credits carried. A 10% excess on claims. No cover while wanted or during your own crime.
- Stolen goods stay marked through their cargo history. Black-market buyers, and police who check.
- Ship energy and damage: fore and aft shields, energy reserves, weapon heat, equipment damage, real enemy missiles and a "Pulse scrubber" countermeasure.
- Side views and more weapon mounts.
- Last-resort kit: a "Drift capsule" escape pod and a single-use "Nullburst charge", with clear rules for cargo, insurance and harm to neutral ships.
- Commander scanner: search for a commander by name, wanted levels on scan results, and flying "dark" with no name broadcast, at the cost of looking suspicious. The server decides who is in range, so a modified game can't reveal everyone.
- Watch beacons: deployable tripwires that message their owner when a chosen commander, ship type or wanted level passes. Limits, expiry and counterplay to be settled first.

**Done when:** piracy pays but carries real risk, and no loot can be duplicated.

## Phase 6 — Credit and crews

**Goal:** banking, groups, and contracts between players.

- Bank loans secured against your ship, with a credit rating from A to E based on repayment history, debt against ship value, account age, recent borrowing and trading record. A criminal record or bad history means a smaller loan or a refusal. Refusals are explained.
- Banks have limited money to lend; lending capacity grows with the number of active ships.
- Repossession contracts: the bank posts defaulters' ships for hunters to bring in.
- Player-to-player loans with agreed terms, recorded and collected by the ledger.
- Player-posted bounties, with server-checked completion and payment.
- Breakdown cover: towing, emergency fuel and repairs, with clear areas and call-out limits.
- Clans with shared funds held on the ledger.
- Selling anything you own (ships, equipment, cargo, storage) to other players, with clear rules on contents, debts and selling your last ship.

**Done when:** lending stays profitable and stable in the economy simulation and in live play.

## Phase 7 — Life on the lanes

**Goal:** the galaxy feels inhabited.

- Departures and arrivals boards at every station.
- Passenger liners (the Brennix Packet Company) as well as freighters.
- Hitching rides on other ships, carrying up to 1 tonne; working your passage.
- Pilots who lose everything earn a basic ship back through station jobs.
- Used ships that are cheaper but come with faults.
- Living traffic: varied freighters, escorts, miners, raiders and bounty hunters with their own hulls and behaviour.
- Riftborn alien encounters and rare interrupted jumps.
- Planet messages for named players, and local noticeboards for wanted and for-sale notices, with expiry and moderation.
- A crowd-written galactic guide.
- Fuel you can trade as cargo.
- **SpaceNet** (parked 2026-11-25, not designed yet): one place in the game to go and look things up. It holds all the manuals and information about the game, and maybe more. Pilots search it for what they need on a mission. It could also carry the Relay's stories (Council decrees, the STA Tally, station news) with their history and what the terms mean, and the used-ship listings, noticeboards and galactic guide above. Today that news only scrolls past on the Relay ticker, and nothing in the game explains its terms.
- **Ship's radio** (parked 2026-11-25, not designed yet): music in the cockpit without the game streaming anything. The middle screen shows what's playing and offers play/pause and skip, by controlling the pilot's own player (MPRIS on Linux, AppleScript for Music and Spotify on macOS), so YouTube Music in a browser, Spotify and the rest all work and the music stays the pilot's. Optionally, in-game radio stations of royalty-free or commissioned tracks. Not YouTube inside the game: its terms allow only its own embedded web player (at least 200×200, ads and branding intact, no audio-only), which would mean building a web browser into the game, and the middle screen is 178 px high.

## Phase 8 — The frontier (1.0)

**Goal:** an unlimited galaxy beyond the core.

- A seeded star atlas: hundreds of generated systems with fixed coordinates, searchable descriptions and their own economies, simulated in detail only where pilots are. Sectors may be linked by a rare single-use "Fold key".
- The economy and the Galactic Council scale to the larger galaxy.
- The 8 core systems stay free forever. A paid tier for the frontier and later ranks is planned; its terms will be published before it ships.

## Phase 9 — Owners and exchange

Ideas, to be designed once the frontier is stable.

- Storage centres with bay rentals; selling bays off-plan to fund new stations.
- Personal bases with defences, owned and robot-crewed fleets, and shipyards. Installations that can be bought, rented or captured under server rules, with tenant protection settled first.
- Any exchange between real money and credits only after full legal review. Nothing like it is enabled today, and nothing will be without published terms.
- **Community worlds** (parked 2026-11-26, not designed yet): players host their own Riftdogs servers and worlds, paying for and moderating them. Riftdogs keeps what must stay central: pilot identity (pilot numbers, commander names and their history, licences), the bank (anything that moves credits between worlds or touches the real world goes through the Phase 4 ledger), the official server list and the brand and merch. A host registers a server for a revocable key; unregistered servers run as private worlds with nothing that carries over. Needs the Phase 4 ledger first, trademark and server licence terms (the code is MIT), and the legal review above for anything tied to real money.

---

## How work flows

- Each phase starts with a written design, then an implementation plan, then the build, with a review on every task.
- Work happens on a branch per release; `main` only holds released code.
- The server is deployed before any game release that depends on it.
- Every release is signed.
- Player feedback comes in through the in-game feedback screen and is triaged before each release.
