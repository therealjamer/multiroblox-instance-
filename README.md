# Changelog

## 3.1

- **Join one specific server.** The game field now also accepts a link
  containing a `gameId`, so a profile can join a chosen server rather than
  whichever one Roblox picks.
- **Unrecognised disconnects are recorded.** The list of reasons auto-rejoin
  understands is a best guess at Roblox's log wording. When a close matches
  nothing, the last 40 log lines are saved to `unknown_exits.log` so the list
  can be corrected from real evidence.
- **Clearer error on the legacy handle path.** That fallback stores PIDs in 16
  bits and cannot match a PID above 65535. It used to find nothing and suggest
  running as Administrator, which is the wrong advice for that cause.
- **A feature that keeps failing switches itself off** instead of throwing
  every few seconds for the rest of the session.

## 3.0

- Reads Roblox's own client log to work out **why** a client closed, and skips
  rejoining after a kick, an idle-kick or a moderation action.
- Mutes every client except the one you are looking at.
- Global hotkeys, `Ctrl+Alt+1..9`, to jump between clients.
- Multi-monitor tiling, with a monitor assignable per profile.
- Saves and restores each account's window position.
- Play history: every session, its length and how it ended, as a CSV.
- Any unexpected error is written to the log file with a full traceback
  instead of closing the window silently.

## 2.1

- Account column, cookie health checks, a remembered launch method, a log file.
- Window tiling, Close Selected / Close All, avatars, encrypted profile
  export/import, per-profile core counts, cookie age.
- Rate-limit handling: a Roblox 429 is reported as rate limiting and retried,
  not misreported as an expired cookie.
- **A failed sign-in no longer falls back to a guest launch.** A guest launch
  opens whichever account the Roblox app already has, which is almost never the
  profile you picked. It is now a per-profile opt-in.
- One-click **Diagnose** report, containing no cookies and no webhook URLs.

## 2.0 — rewrite of the original script

The original version could not start: the card helper packed its title into
the same frame that callers then used `grid()` on, which raises
`TclError: cannot use geometry manager "grid"` before the window appears.

Fixed alongside it:

- **The lock was only released after a launch, never before.** Whichever client
  created the single-instance lock owns it, so a new client quit instantly
  while an existing one was running. This was the reason multi-instance did not
  actually work.
- **PIDs above 65535 could never match** in the handle scan — the legacy
  structure stores them in 16 bits, and Windows hands out larger PIDs
  routinely. Unlocking silently did nothing and blamed permissions.
- **Only one unlock attempt was made, immediately after launch**, before Roblox
  had created the lock. Now retried.
- **Any password unlocked an empty profile store**, then re-encrypted the
  profiles under the wrong key. An encrypted verification blob now proves the
  password before anything is written.
- **Changing the master password wrote the new salt first.** A failure between
  the two writes left the profile store permanently unreadable. Now written
  with a backup and a read-back check.
- **Profile writes were not atomic** — a crash mid-write corrupted the store.
- **The watcher ran on the UI thread** and turned itself off after one
  instance. It now runs in the background and stays on until switched off.
- **Worker threads read Tk variables**, which is not thread-safe.
- The activity log grew without bound; `cryptography` being absent stopped the
  app entirely rather than disabling only the account saver.
