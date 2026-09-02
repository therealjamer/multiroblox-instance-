# Security

This program handles Roblox session cookies, which are equivalent to account
passwords. If you find a way for it to leak one, please report it before
posting publicly.

**How to report:** open a GitHub security advisory (Security tab → Report a
vulnerability), or email the address on my profile. I would rather hear about
it awkwardly than read about it later.

## What the program does with your cookies

- Stored in `%AppData%\MultiRobloxGUI\profiles.enc`, encrypted with a key
  derived from your master password (PBKDF2-HMAC-SHA256, 390,000 iterations,
  random 16-byte salt, Fernet/AES-128-CBC + HMAC).
- Sent only to `auth.roblox.com` (to get a launch ticket) and
  `users.roblox.com` (to check which account a cookie belongs to), over HTTPS.
- Never written to the activity log, the log file, or the diagnostics report.
  There are tests asserting the diagnostics report contains no cookie and no
  alert webhook.
- Exports are encrypted under a separate password you choose.

## What it does not protect against

- **Anything running as you on your own machine.** Once unlocked, cookies are
  in the process's memory. This protects the file at rest, not a compromised
  PC.
- **A forgotten master password.** There is no recovery and no backdoor.
- **Roblox rotating or invalidating cookies**, which it does regularly.
