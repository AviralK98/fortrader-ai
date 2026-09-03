## Installing on macOS — read this first

Drag **Fortrader AI** to Applications, then open Terminal and run:

```
xattr -dr com.apple.quarantine "/Applications/Fortrader AI.app"
```

It prints nothing when it works. Launch the app normally afterwards.

**Without that step macOS will say “Fortrader AI” is damaged and can’t be
opened, and offer only Move to Bin.** Nothing is damaged. This build has
no Apple Developer ID — that requires a paid membership — and the message
above is how macOS refuses an app it cannot attribute to a certified
developer. The command clears the “downloaded from the internet” marker
so macOS stops asking Apple about it. No password, nothing else affected,
once per installed version.

Right-click → Open, and System Settings → Privacy & Security → **Open
Anyway**, do not work here. Those are offered only for apps that carry a
developer certificate but have not been reviewed by Apple.

Apple Silicon only. The `.dmg` also contains `READ ME FIRST.txt` with the
same instructions.

## Installing on Windows

Run the `.exe`. SmartScreen will warn once because the installer is
unsigned — choose **More info → Run anyway**. Installs per-user, no admin
prompt.

---
