# Changelog

## Unreleased

- **Frozen/hung instance detection.** Off by default. Uses the same signal
  Task Manager uses for "Not Responding" - if a launched client stops
  responding for a configurable number of seconds, it's restarted (the
  existing rejoin machinery takes it from there).
- **Bulk profile import.** Paste several accounts at once as `Name,Cookie`
  lines (the name is optional) instead of adding them one by one. Warns
  about short/malformed cookies in a single summary rather than one dialog
  per line, and can tag the whole batch with a group in one go.
- **Profile groups/tags.** Give a profile an optional group (e.g. "Farming",
  "Alts") and filter the account list down to just that group with a
  dropdown next to the existing text search - the two filters combine.
- **In-app scheduler**, a new tab. Launch a saved profile at a chosen time
  of day, optionally only on certain days of the week, without needing
  Windows Task Scheduler. Only runs while MultiRoblox is open.
- **A better updater.** The update banner now has a second option,
  "Download & Verify", alongside the existing link to the release page.
  It downloads the new build in the background, checks it against the
  SHA-256 that the release workflow publishes in the release notes, and
  deletes it automatically if the hash doesn't match. Deliberately does
  NOT replace the running exe or launch anything itself - antivirus gets
  a normal downloaded file to scan rather than a process replacing
  itself, and a bad download can't take out a working install. The
  verified file is revealed in Explorer when it's done; run it yourself
  whenever you're ready.

## 3.5

- **Fixed: a signed-in launch method that stopped working could get stuck
  as "the one that works," forever.** `auto` mode remembers whichever
  method (`handler`/`uri`/`legacy`/`redeem`) last succeeded, so it doesn't
  re-test all four every launch - but the check deciding "did this actually
  work" only waited 2 seconds, and a real failure (Roblox's own installer/
  relaunch hand-off failing, seen directly in Roblox's own log as "Critical:
  failed to start client App") can land a couple of seconds past that. Once
  a method got remembered this way, `auto` kept reusing it forever and
  never re-tried the others - looking exactly like "it only launches one
  instance now," even on machines that don't use Bloxstrap. Fixed two ways:
  the check now waits 5 seconds, and a remembered method that fails gets
  forgotten immediately instead of staying stuck.

## 3.4

- **A test suite**, run automatically on every push via GitHub Actions
  (separate from the release build, which only runs on a version tag).
  Covers the update-checker's version comparison, game-link parsing, cookie
  cleanup, the CPU-rate math, the SMT-aware core-spreading stride, and the
  profile search/filter's index mapping.
- **"Optimize for a Low-End PC" preset** in Settings, plus a configurable
  refresh interval for MultiRoblox's own instance-list polling (was a fixed
  3 seconds) - useful on a weaker CPU where that overhead is proportionally
  bigger.
- **Tried, then reverted: building with `--uac-admin`** (forced elevation on
  every launch). Every Roblox client MultiRoblox starts inherits its
  parent's elevation, and Roblox's own updater/bootstrapper does not handle
  running elevated well - it failed outright with its own "Installer
  encountered a critical error" dialog, breaking multi-instance launching
  entirely. The release build is back to running as a normal user; use the
  existing "Restart as Administrator" option in Settings if the unlock step
  specifically needs it on your system.

## 3.2

- **Hard CPU cap**, on top of core affinity. Affinity only says which cores a
  client may use; a client "limited" to 2 cores could still peg both at 100%.
  A Windows Job Object now caps how much of them it may actually use.
- **Core spreading is now physical-core aware.** `os.cpu_count()` and the
  affinity mask both count logical (hyperthread) processors, so spreading
  across logical IDs alone could quietly put two instances on the same
  physical core's two threads. Now strides by the SMT ratio instead.
- **The frame-rate cap self-heals.** If something external undoes it mid-
  session (a Roblox self-update, a bootstrapper's own FPS setting), it's
  now re-checked and reapplied automatically instead of only at launch.
- **Settings no longer fsync on every keystroke.** Typing in the notify-
  webhook field (and similar) used to write to disk on every character.
  Now debounced.
- **One process scan per refresh tick instead of three.** The instance list,
  background-priority, and audio-focus steps each independently scanned
  every process on the system every 3 seconds; now they share one snapshot.
- **Profile search/filter box** on the Launcher tab - useful once you have
  more than a handful of saved accounts.
- **Update checker.** Checks GitHub Releases on startup and shows a banner
  when a newer version is available.
- **Silent command-line launch**, for a desktop shortcut or Task Scheduler:
  `--launch-all`, `--launch "Profile Name"`, `--minimized`.
- **Appearance settings**: accent color, font, and UI scale, all changeable
  in Settings (applies on restart).
- **Periodic screenshots to a Discord webhook**, off by default. Every N
  minutes, captures each running Roblox window directly (via `PrintWindow`,
  not a screen grab - works even if a window is minimized or covered) and
  posts them to the same Discord webhook the phone alerts already use.

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
