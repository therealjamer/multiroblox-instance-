# Release description template

Paste this into the GitHub release, filling in the blanks.

---

**MultiRoblox 3.0** — run several Roblox clients at once, each on its own
account and game.

### Download

`MultiRoblox.exe` below. Nothing else needed — Python and all dependencies are
bundled. Windows only.

### Verify it

- SHA-256: `<paste: certutil -hashfile dist\MultiRoblox.exe SHA256>`
- VirusTotal: `<paste link>`

Expect some detections. This program releases another process's single-instance
lock handle, which is genuinely the technique cheat tools use, so heuristic
scanners react to it. The full source is in this repo and `build.bat`
reproduces the exe — if you would rather not trust a binary, build your own.

### What's in this release

- <!-- what changed -->

### Reminders

- Multi-instancing and cookie sign-in are against Roblox's Terms of Use.
  Accounts have been actioned for both. Your accounts, your risk.
- A `.ROBLOSECURITY` cookie is full account access. Only use accounts you own,
  and never share your `profiles.enc` or an exported backup.
- Forgetting your master password means losing your saved accounts. There is
  no recovery.
