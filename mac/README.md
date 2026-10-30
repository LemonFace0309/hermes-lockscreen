# Hermes Lock Screen with a Mac

An exact copy of your chat on the Lock Screen. If you have a Mac that stays on and has your Messages, it can read the
conversation straight from Messages and draw the Lock Screen there. The iPhone only asks the Mac for the picture and
sets it. So the Lock Screen has exactly what Messages has: both sides, tapbacks as they are now, edits, and your
voice notes with your words. The Mac draws a picture in about a fifth of a second.

```
Messages on the Mac ──reader──▶ chat.json ──server──▶ picture ◀── Tailscale ── iPhone: Hermes Lock Screen ──▶ Lock Screen
```

## What you need

- A Mac that stays on (a Mac mini is ideal), on macOS 14 or newer, with Xcode's command line tools
  (`xcode-select --install`) and Python 3.
- Messages on that Mac signed in to **your** Apple Account: the one you text your agent from.
- Your agent saved as a contact on the Mac, with its phone number or email.
- [Tailscale](https://tailscale.com) (free) on the Mac and on the iPhone, signed in to the same account. It lets your
  iPhone reach the Mac from any network, encrypted.
- An iPhone on iOS 26 or newer, with the **Hermes** folder from [step 1 of the README](../README.md#1-get-the-files)
  (for the wall photo and Talk to Hermes).

## How it works

- `hermes-wall-reader` copies your conversation with the agent out of Messages' database about once a second when it
  changes. It's the only part with Full Disk Access, it reads only that conversation, and it never logs a message's
  words.
- `hermes-wall` draws the chat with the design in `design/tokens.json` and the walls in `assets/`, and serves the
  picture on port 7337. Every request needs the token from the Mac's `config.json`.
- On the iPhone, **Hermes Lock Screen** sends the Mac what started it (`{"input": …}`): your agent's message, your
  voice note's words, or nothing. It sets the picture it gets back. For your agent's message or your voice note, the
  Mac first waits (up to 10 seconds) until that message has reached it. Anything other than a picture (the Mac is off,
  no connection) leaves your Lock Screen as it was.

## Set up the Mac

1. Get the code:
   ```bash
   git clone https://github.com/LemonFace0309/hermes-lockscreen.git && cd hermes-lockscreen
   ```
2. Check that Messages on this Mac is signed in to your Apple Account: **Messages › Settings › iMessage**. If it's
   signed in as your agent, "you" and "your agent" swap sides, and that isn't handled.
3. Install, with your agent's name exactly as its contact is called:
   ```bash
   ./mac/install.sh "Hermes"
   ```
   This builds the two programs, writes `~/Library/Application Support/Hermes Wall/config.json` with a new token, and
   starts two launch agents, `local.hermeswall.reader` and `local.hermeswall.server`. Logs go to
   `~/Library/Logs/Hermes Wall/`.
4. Give the reader Full Disk Access, so it can read Messages:
   1. Open **System Settings › Privacy & Security › Full Disk Access**.
   2. Click **+** under the list and confirm with Touch ID or your password.
   3. Press **⌘⇧G**, type `~/Applications`, press Return, pick **Hermes Wall Reader** and click **Open**.
   4. Check that its switch is on.

   Then check it:
   ```bash
   cat ~/Library/Application\ Support/Hermes\ Wall/reader-status.json
   ```
   It should say `"ok": true` and how many messages it copied. If it says `no chat with … found`, the name doesn't
   match a contact with a number: put the agent's number or email in `handles` in `config.json`, for example
   `"handles": ["+15551234567"]`.
5. Install Tailscale on the Mac (Mac App Store, or `brew install --cask tailscale`) and sign in. Keep **MagicDNS** on
   (it is by default).
6. Build the iPhone's Hermes Lock Screen. It points at this Mac and carries its token:
   ```bash
   python3 mac/build_phone_shortcut.py .local/hermes-wall --tailscale
   ```
   It prints `Hermes Lock Screen: 31 actions, asks http://<your-mac>.<your-tailnet>.ts.net:7337/wall`.
   - Only ever on the same Wi-Fi as the Mac? Leave out `--tailscale` to use the Mac's `.local` name.
   - If your Tailscale runs with its own socket, `--tailscale` can't find it: pass
     `--url http://<your-mac>.<your-tailnet>.ts.net:7337/wall` instead.
   - The shortcut holds your Mac's token. Don't share it, and don't commit `.local/`.
7. Get it to the iPhone. AirDrop `.local/hermes-wall/Hermes Lock Screen.shortcut`, or put it in the Hermes folder in
   iCloud Drive (this replaces the one from Hermes.zip):
   ```bash
   cp ".local/hermes-wall/Hermes Lock Screen.shortcut" ~/Library/Mobile\ Documents/iCloud~is~workflow~my~workflows/Documents/Hermes/
   ```

Keep the Mac awake and logged in: the two programs run while you're logged in. On a Mac mini, turn on **System
Settings › Energy › Prevent automatic sleeping when the display is off**.

## Set up the iPhone

1. **Tailscale.** Install Tailscale from the App Store and sign in to the same account as on the Mac, **with the same
   sign-in** (signing in with Apple on one and Google on the other makes two separate tailnets). Allow the VPN setup
   and leave it on: it reconnects by itself. Your Mac should be in its list of devices.
2. **The wall.** If you haven't yet, do [steps 1 and 2 of the README](../README.md#set-it-up): the Hermes folder and a
   Lock Screen made from `wall.png`.
3. **Add the shortcuts.** In **Files › iCloud Drive › Shortcuts › Hermes** (or from AirDrop), tap **Hermes Lock
   Screen** and tap **Add Shortcut**. If you already have one, choose **Replace**, on the iPhone: your automations
   keep running it. Add **Talk to Hermes** too if you want the Action button. You don't need Hermes Chat Renderer.
4. **Pick the Lock Screen.** In **Shortcuts**, on **Hermes Lock Screen** tap **···**. In its **Set Wallpaper Photo**
   action, tap the wallpaper and choose the Lock Screen from step 2. Tap **Done**.
5. **Run it once.** Tap the **Hermes Lock Screen** tile. When it asks to connect to your Mac, tap **Always Allow**:
   an automation can't ask, so it would stall. Lock your iPhone: your chat is there.
6. **Update when your agent texts.** Add the Message automation from
   [step 6 of the README](../README.md#6-make-it-update-by-itself).
7. **Change the wall with the time of day.** The Mac picks the wall by its clock: dawn from 5:00, daylight from 8:00,
   golden hour from 17:00, moonlight from 20:00. Add four automations to redraw then: in Shortcuts, **Automation › +
   › Time of Day**, the exact time, **Daily**, **Run Immediately**, **Notify When Run** off, then **New Blank
   Automation › Add Action › Run Shortcut › Hermes Lock Screen**, with no input.
8. **Talk with the Action button** (optional): **Settings › Action Button › Shortcut › Talk to Hermes**. It sends a
   voice note, and the Lock Screen shows your words under it.

## Check it

```bash
curl -s http://localhost:7337/health
```
```bash
tail -f ~/Library/Logs/Hermes\ Wall/server.log
```

Each update from the iPhone is one line, for example `POST /wall → 200 1013322 bytes in 118 ms (waited for it)`:

| Note | Meaning |
|---|---|
| `now` | A run by hand or a Time of Day automation: drawn at once. |
| `waited for it` | Your agent's message or your voice note: drawn once the Mac had it. |
| `nothing new in 10 s` | Nothing newer reached the Mac in 10 s. Usually an earlier update already drew it. |

To see the picture on the Mac: `mac/.build/release/hermes-wall render wall.jpg` draws the chat once, the same way the
server does. `mac/.build/release/hermes-wall sample out.png` draws a made-up chat, to check the drawing without
Messages.

## Good to know

- **Your own messages show with your agent's next tapback or reply.** iOS runs automations only for messages you
  receive. Agents that react 👀 while they work bring yours within seconds.
- **A tapback that arrives while you have your agent's chat open in Messages may not run the automation.** Your
  message then shows with the next one.
- **Voice notes show your words only when Talk to Hermes sent them.** Messages doesn't store a transcript; the Mac
  keeps the words Talk to Hermes sends in `transcripts.json`.
- **One agent at a time** (`agent` in `config.json`).
- Your chat stays on your Mac and your iPhone. Tailscale encrypts the connection, and the Mac answers only requests
  with the token.

## Updating and stopping

- After getting new code, run `./mac/install.sh` again (no name needed). It replaces the reader only when the
  reader's own code changed (`mac/Sources/hermes-wall-reader`, `mac/Sources/ChatModel`). macOS ties Full Disk Access
  to the exact build, so a new reader needs step 4 again.
- The token stays in `config.json`, so the iPhone's shortcut only needs rebuilding when the Mac's address changes.
- To stop it:
  ```bash
  launchctl bootout gui/$UID/local.hermeswall.reader
  ```
  ```bash
  launchctl bootout gui/$UID/local.hermeswall.server
  ```
  They start again at your next login unless you also remove `~/Library/LaunchAgents/local.hermeswall.*.plist`.
