name: Build and release

# Builds MultiRoblox.exe on GitHub's own Windows runner and attaches it to a
# GitHub Release - not the repo itself. Releases have no file-size limit;
# the repo's own "Add file" uploader is what capped you at 25MB.
#
# To ship a new version:
#   1. Bump APP_VERSION in multi_roblox.py to match the tag you're about
#      to push (e.g. APP_VERSION = "3.2" for tag v3.2). The build fails
#      on purpose if these don't match - it's cheap insurance against
#      shipping an exe that reports the wrong version.
#   2. git tag v3.2 && git push origin v3.2
#   3. Watch the Actions tab; the release appears automatically when it's
#      done, with MultiRoblox.exe attached and its SHA-256 in the notes.

on:
  push:
    tags:
      - "v*"

permissions:
  contents: write

jobs:
  build-and-release:
    runs-on: windows-latest
    steps:
      - name: Check out the repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Confirm APP_VERSION matches the tag
        shell: pwsh
        run: |
          $tag = "${{ github.ref_name }}" -replace '^v', ''
          $match = Select-String -Path multi_roblox.py -Pattern '^APP_VERSION = "([^"]+)"'
          if (-not $match) {
            Write-Error "Could not find APP_VERSION in multi_roblox.py."
            exit 1
          }
          $inFile = $match.Matches[0].Groups[1].Value
          if ($inFile -ne $tag) {
            Write-Error "Tag is v$tag but APP_VERSION in multi_roblox.py is `"$inFile`". Bump APP_VERSION to match before tagging, then re-push the tag."
            exit 1
          }
          Write-Host "APP_VERSION ($inFile) matches tag ($tag) - continuing."

      - name: Install dependencies
        run: python -m pip install --upgrade -r requirements-dev.txt

      - name: Build MultiRoblox.exe
        run: >
          python -m PyInstaller --noconfirm --clean --onefile --windowed
          --icon MultiRoblox.ico
          --collect-all cryptography --collect-all psutil --collect-all requests
          --collect-all pystray --collect-all PIL --collect-all pycaw
          --name MultiRoblox multi_roblox.py

      - name: Write release notes (with SHA-256)
        shell: pwsh
        run: |
          $hash = (Get-FileHash dist\MultiRoblox.exe -Algorithm SHA256).Hash
          "SHA-256 of MultiRoblox.exe: $hash" | Out-File -FilePath release_notes.txt -Encoding utf8
          "" | Out-File -FilePath release_notes.txt -Encoding utf8 -Append
          "See CHANGELOG.md for what changed in this version." | Out-File -FilePath release_notes.txt -Encoding utf8 -Append

      - name: Create GitHub Release
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: >
          gh release create "${{ github.ref_name }}"
          dist\MultiRoblox.exe
          --title "MultiRoblox ${{ github.ref_name }}"
          --notes-file release_notes.txt
