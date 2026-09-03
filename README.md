# MultiRoblox

Run several Roblox clients at once on Windows, each signed into a different
account and sent to a different game or private server.

Roblox allows one client at a time and enforces it with a single-instance
lock. MultiRoblox releases that lock so more clients can start, then manages
the ones that are running — CPU cores, frame rate, window layout, audio focus
and rejoining after a drop.

Not affiliated with, endorsed by, or connected to Roblox Corporation.

---

## Read this before you use it

- **Running several clients at once is against Roblox's Terms of Use, and so
  is signing in with a session cookie.** Accounts have been actioned for both.
  Leaving accounts rejoining unattended for hours looks like an AFK farm,
  which is the pattern most likely to get noticed. Your accounts, your risk.
- **A `.ROBLOSECURITY` cookie is full access to an account** — no password, no
  2FA. Only ever use accounts you own. Never send anyone your cookie, your
  `profiles.enc`, or an exported backup.
- **Antivirus will probably flag the build.** Releasing another process's lock
  handle is genuinely the technique cheat tools use, so scanners react to it.
  The source is here so you don't have to take that on trust — read it, or
  build it yourself.
- **There is no warranty.** See [LICENSE](LICENSE).

---

## What it does

| | |
|---|---|
| **Multi-instance** | Releases the single-instance lock so more clients can start. A watcher switch does it automatically for any client you open. |
| **Accounts** | Save a profile per account. Cookies are encrypted at rest with a master password (PBKDF2-SHA256, 390k iterations, Fernet). |
| **Per-profile games** | A place ID, a game URL, a private server link, or a link to one specific server. Each account goes where you send it. |
| **Auto-rejoin** | Relaunches a client that closed. Reads Roblox's own log first: it rejoins after a crash or a dropped connection, but not after a kick, an idle-kick or a moderation action. |
| **CPU** | Core limits (global or per profile), spread across *physical* cores rather than hyperthread siblings, below-normal priority for clients you aren't looking at, and an optional hard cap on how much CPU each client may actually use. |
| **Frame rate** | Caps FPS via Roblox's own `ClientAppSettings.json`. 30 fps saves a lot with several clients open, and the cap is reapplied if anything overwrites it. |
| **Windows** | Tile in a grid, columns or rows, across multiple monitors. Save each account's window position and have it restored on launch. |
| **Audio** | Mutes every client except the one you're looking at. |
| **Hotkeys** | `Ctrl+Alt+1..9` jumps to a client. |
| **Alerts** | Phone notifications via ntfy or a Discord webhook when a profile needs you. |
| **History** | Every session — account, duration, how it ended — as a CSV. |
| **Diagnostics** | One button writes a full report for troubleshooting. Contains no cookies. |

## What it does not do

It never reads the game screen and never sends clicks or keystrokes into a
client. Nothing is injected into the Roblox process. On its own it does
exactly one thing to a running client: closes its single-instance lock handle
so the next client can start.

It can close clients, but only from the Close Selected / Close All buttons,
only the ones you picked, and never automatically.

---

## Install

Download `MultiRoblox.exe` from [Releases](../../releases). Nothing else is
needed — Python and every dependency are bundled.

Windows SmartScreen will warn about it because it is unsigned. If you would
rather not trust a binary from a stranger, build it yourself — it takes two
minutes and the instructions are below.

## Build it yourself

Requires Windows and Python 3.10+.

```bat
pip install psutil requests cryptography pyinstaller pystray pillow pycaw
pyinstaller --noconfirm --clean --onefile --windowed --icon MultiRoblox.ico ^
  --collect-all cryptography --collect-all psutil --collect-all requests ^
  --collect-all pystray --collect-all PIL --collect-all pycaw ^
  --name MultiRoblox multi_roblox.py
```

The result is `dist\MultiRoblox.exe` (about 28 MB). Or just run the script
directly:

```bat
python multi_roblox.py
```

`pystray`, `pillow` and `pycaw` are optional — without them the tray icon and
audio muting are unavailable and everything else works. `psutil`, `requests`
and `cryptography` are required for the instance list, signed-in launches and
the account saver respectively.

### Affinity vs. the hard cap

These are two different things and they work together:

- **Core limit (affinity)** decides *which* cores a client is allowed on. A
  client limited to two cores can still run both at 100%.
- **Hard-cap CPU** (Settings, a percentage of one core) decides *how much* it
  may actually use. Windows enforces it directly through a job object.

Use affinity to keep clients out of each other's way, and the hard cap when
you want a guaranteed ceiling — for example, keeping four background accounts
from touching the headroom of whatever you are actually playing.

---

## First run

1. Set a master password. It encrypts your saved accounts on this PC.
   **There is no recovery** — forget it and your saved cookies are gone.
2. Add a profile with the account's cookie (below).
3. Give it a game, click Launch.

### Getting a cookie

1. Open a **private / incognito window** and log into roblox.com as that
   account.
2. `F12` → **Application** → Storage → Cookies → `https://www.roblox.com`
3. Find `.ROBLOSECURITY`, double-click its Value, `Ctrl+A`, `Ctrl+C`. It is
   800+ characters — make sure you get all of it.
4. Paste it into the profile and click **Test Cookie**. You want
   `valid - signed in as <name>`.
5. **Close the private window. Do not click Log Out** — logging out
   invalidates the cookie you just copied.

Do each account in its own private window. Logging into a second account in
the same window kills the first account's cookie.

---

## Troubleshooting

Press **Diagnose** in Settings. It writes a full report — dependencies, your
Roblox install, which program handles launches, and every profile's cookie
status — and copies it to your clipboard. It contains account names but no
cookies and no webhook URLs, so it is safe to paste into an issue.

| Symptom | Cause |
|---|---|
| `cookie rejected (HTTP 401)` | The cookie expired, or you logged out after copying it. Re-copy it in a private window. |
| `Roblox is rate limiting` | Too many sign-ins at once. Wait a minute; raise **Gap between sign-ins**. Not a dead cookie. |
| Client closes right after launching | Set a game on the profile. `launchmode:play` is far more reliable than the app home page. |
| `Could not find the singleton lock` | Try running as Administrator. |
| Nothing happens on launch | If you use Bloxstrap, check whether its own multi-instance option is also on. Use one or the other, not both. |
| Sign-in fails and nothing launches | Deliberate. A guest launch would open whichever account Roblox already has, not the one you picked. There's a per-profile opt-in if you want that. |

Logs live in `%AppData%\MultiRobloxGUI\log.txt`.

---

## Where your data lives

Everything is on your own machine, in `%AppData%\MultiRobloxGUI`:

| File | What |
|---|---|
| `profiles.enc` | Your accounts, encrypted with your master password |
| `auth.json` | Salt and a verification blob — no cookie material |
| `settings.json`, `layouts.json`, `sessions.csv`, `log.txt` | Settings, window positions, play history, logs |

Nothing is sent anywhere except Roblox's own API (to sign in and to look up
game names) and, if you turn alerts on, the ntfy or Discord endpoint you
configured.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE).
