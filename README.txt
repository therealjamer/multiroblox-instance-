MultiRoblox - run several Roblox clients at once
====================================================

WHAT IT DOES
  Roblox normally allows one client at a time. It enforces that with a
  single-instance lock. MultiRoblox releases that lock so a second (third,
  fourth...) client can start, and can sign each one into a different account
  and send it to a different game or private server.

  It never reads the screen and never sends clicks or keystrokes into the
  game. The only thing it does to a running client on its own is close that
  one lock handle. It can close clients too, but only when you press Close
  Selected or Close All yourself.


FIRST RUN
  1. Run MultiRoblox.exe. Windows SmartScreen may warn about it - it is
     unsigned. ("More info" -> "Run anyway".)
  2. Set a master password. This encrypts your saved accounts on this PC.
     THERE IS NO RECOVERY - if you forget it, your saved accounts are gone.
  3. The main window opens.


ADDING AN ACCOUNT
  Each account is saved as a "profile" holding a name, a Roblox session
  cookie, and optionally a game to join.

  To get the cookie:
  1. Open a PRIVATE / INCOGNITO window (Ctrl+Shift+N) and log into
     roblox.com as that account.
  2. Press F12 -> "Application" tab -> Storage -> Cookies ->
     https://www.roblox.com
  3. Find .ROBLOSECURITY. Double-click its Value, Ctrl+A, Ctrl+C.
     It is very long (800+ characters) - make sure you copy all of it.
  4. In MultiRoblox: Add -> paste it -> name the profile -> Save.
  5. Click "Test Cookie". You want "valid - signed in as <name>".
  6. CLOSE the private window. Do NOT click Log Out - logging out
     invalidates the cookie you just copied.

  Do each account in its own private window. Logging into a second account
  in the same window kills the first account's cookie.

  A cookie is full access to that account - no password, no 2FA. Only save
  accounts you own. Never send anyone your cookie or the profiles.enc file.


CHOOSING A GAME
  In the profile, "Game to join" accepts any of:
    606849621
    https://www.roblox.com/games/606849621/Natural-Disaster-Survival
    a private server link containing privateServerLinkCode=...
    a link to one specific server (contains a gameId)
  Leave it blank to open the Roblox app home page instead of a game.
  Joining a game directly is more reliable than the home page.


LAUNCHING
  - Select profiles and click "Launch Selected Profiles", or "Launch All".
  - Turn the WATCHER switch on (top right) and any Roblox window you open by
    any other means gets unlocked automatically.
  - "Launch Guest Instance" starts Roblox without signing in - it uses
    whichever account is already logged into the Roblox app.


AUTO-REJOIN
  Tick "Rejoin automatically" on a profile. If its client closes while the
  watcher is on, MultiRoblox waits and relaunches it.
  It stops after 5 quick failures in a row so a broken profile cannot loop
  forever. A client that stayed up 5+ minutes resets that count. Launching by
  hand also resets it.


PHONE ALERTS (optional)
  Settings -> Alerts. Two options, neither needs an account:
    ntfy    - install the "ntfy" app, pick a hard-to-guess topic name, put the
              same name in MultiRoblox and subscribe to it in the app.
    discord - paste a channel webhook URL.
  "Send Test Alert" confirms it works. By default you are only alerted when a
  profile gives up rejoining.


MANAGING WINDOWS
  Instances tab -> Tile Grid / Columns / Rows arranges every open client so
  they do not overlap.
  "Close Selected" / "Close All" shut clients down. Nothing is ever closed
  automatically - only when you press one of those buttons - and closing this
  way does not trigger auto-rejoin.


FRAME RATE
  Settings -> Frame rate cap. 30 fps saves a lot of CPU and GPU when several
  clients are open. It writes Roblox's own setting, so it applies to EVERY
  client on the PC (including the one you are playing), and Roblox clears it
  when it updates - MultiRoblox re-applies it at each launch.
  If you use Bloxstrap, it has its own FPS setting; use one or the other.


CPU LIMITS - TWO DIFFERENT THINGS
  Core limit (affinity) decides WHICH cores a client may use. A client limited
  to two cores can still run both of them at 100%.
  Settings -> "Hard-cap CPU per instance" decides HOW MUCH it may actually
  use, as a percentage of one core, enforced by Windows itself. 0 = off.
  Use affinity to keep clients out of each other's way; use the hard cap when
  you want a guaranteed ceiling for background accounts.

  Core spreading now steps whole physical cores, so two instances do not land
  on two hyperthread siblings of the same physical core.


SOUND, HOTKEYS AND MONITORS
  Settings -> "Mute every client except the one you are looking at" silences
  the background clients as you switch windows. (Needs pycaw in the build.)
  Settings -> "Global hotkeys" turns on Ctrl+Alt+1..9 to jump straight to a
  client, in the order the Instances list shows them.
  Each profile can be pinned to a monitor (Edit -> Monitor). Tiling then puts
  each account's windows on its own screen.


WINDOW POSITIONS
  Drag your clients where you want them, then Instances -> "Save Positions".
  Each account's window is put back there automatically on the next launch.
  "Restore Positions" re-applies them to what is open now.


PLAY HISTORY
  The History tab lists every session: when it started, which account, how
  long, and how it ended. Totals per account are shown at the top, and the raw
  data is a CSV you can open in a spreadsheet.


WHY A CLIENT CLOSED
  When a client disappears, MultiRoblox reads Roblox's own log file to work
  out why. A crash or a dropped connection is worth rejoining; being kicked,
  idle-kicked or moderated is not, so it does not rejoin those and tells you
  instead. Turn this off in Settings if you would rather it always rejoin.

  The list of reasons it recognises is a best guess at Roblox's wording. When
  a close does not match anything, the last 40 log lines are saved to
  unknown_exits.log in the config folder. If auto-rejoin ever guesses wrong,
  send that file - it holds the real wording, so the list can be corrected
  from evidence rather than guesswork.


BACKING UP YOUR ACCOUNTS
  Settings -> Export Profiles saves an encrypted backup under a password you
  choose - for moving to a new PC. The file holds live cookies: keep it
  private, never send it to anyone. Import Profiles reads it back.


IF SIGN-IN FAILS
  MultiRoblox will NOT quietly open a different account. A guest launch signs
  in as whoever the Roblox app already has, which is almost never the profile
  you clicked, so a failed sign-in stops and tells you why. If you actually
  want that behaviour for a profile, tick "If sign-in fails, fall back to a
  guest launch" in that profile.

  Launching many accounts at once can trip Roblox's rate limiter. The app
  spaces sign-ins out (Settings -> "Gap between sign-ins") and waits and
  retries when it sees a rate-limit reply, so "rate limiting" in the log means
  wait a minute - it does NOT mean your cookie is dead.


IF SOMETHING GOES WRONG
  Settings -> "Diagnose" writes a full report - dependencies, Roblox install,
  which program handles launches, and every profile's cookie status - and
  copies it to your clipboard. It contains account names but NO cookies and no
  alert webhook, so it is safe to paste to whoever is helping you.

  Settings -> "Open Log File" (%AppData%\MultiRobloxGUI\log.txt). Send that
  file - it says exactly what happened.

  Common ones:
    "cookie rejected (HTTP 401)"  - the cookie expired or you logged out.
                                    Re-copy it in a private window.
    "Could not find the singleton lock" - try running as Administrator.
    Client closes right after launching - set a Place ID on the profile.
    Nothing happens on launch      - check whether Bloxstrap's own
                                    multi-instance option is also enabled.
                                    Use one or the other, not both.


THINGS WORTH KNOWING
  - Running several clients at once is against Roblox's Terms of Use, as is
    signing in with a session cookie. Accounts have been actioned for this.
    Leaving accounts rejoining unattended for hours looks like an AFK farm,
    which is the pattern most likely to be noticed. Your accounts, your call.
  - Antivirus may flag this. Releasing another process's lock handle is a
    technique cheat tools also use, so scanners react to it.
  - Your saved accounts live encrypted in %AppData%\MultiRobloxGUI on YOUR PC
    only. The .exe contains no accounts, so sharing it is safe.
