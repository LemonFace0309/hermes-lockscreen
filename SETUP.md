# Hermes Lock Screen

Your conversation with your agent, drawn as the Lock Screen wallpaper: hold the Action button to talk, glance at the
Lock Screen for the answer. Three shortcuts do it, all in **iCloud Drive › Shortcuts › Hermes**:

| Shortcut | What it does |
|---|---|
| **Hermes Lock Screen** | Updates the wallpaper. Your automations run it, and so does Talk to Hermes. |
| **Hermes Chat Renderer** | Keeps the chat and draws it. You never open it. |
| **Talk to Hermes** | For the Action button: records a voice note, sends it, then adds your words under it. |

**Have a Mac that stays on with your Messages?** [mac/README.md](mac/README.md) sets up an exact copy of the chat
instead: the Mac reads Messages and draws, and the iPhone only fetches the picture. These steps are for the iPhone-only
version.

These steps are for iOS 26, where automations have their own tab. iOS 27 does a few steps differently, as listed
under [iOS 27](#ios-27). To see which you have: **Settings → General → About → iOS Version**.

## Install

### 1. Give it a photo Lock Screen to draw on

Set Wallpaper can only replace a Lock Screen made from a single photo. It can't replace Photo Shuffle, Live Photo,
People, Weather, Astronomy or color Lock Screens.

1. In **Files → iCloud Drive → Shortcuts → Hermes**, tap **wall.png**, tap Share, then **Save Image**.
2. **Settings → Wallpaper → Add New Wallpaper → Photos**, choose that image and tap **Add**. Then tap **Set as
   Wallpaper Pair**, or **Customize Home Screen** to keep a different Home Screen. The shortcut only ever changes the
   Lock Screen.
3. Make it your current Lock Screen. Keep it a plain photo: no filter, and no depth or spatial effect.
4. Back in Files, touch and hold the **Hermes** folder and choose **Keep Downloaded**, if your iPhone offers it. Updates
   then work without a connection.

### 2. Add the three shortcuts

In the same **Hermes** folder, tap each `.shortcut` file and choose **Add Shortcut**:

- **Hermes Chat Renderer** first. When it asks for your agent's contact, type the name exactly as Messages shows it,
  for example `Hermes`.
- **Hermes Lock Screen**.
- **Talk to Hermes**. Pick your agent's contact when it asks.

If one offers to **Replace**, an older copy is still installed: choose **Replace**.

### 3. Pick the Lock Screen

1. In Shortcuts, open **Hermes Lock Screen** for editing: tap **···** on its tile, or touch and hold it and choose
   **Edit**.
2. Scroll to the **Set Wallpaper Photo** action. The note above it starts "Tap "Wallpaper" below", and it's the only
   one.
3. Tap its wallpaper and choose the Lock Screen from step 1. Leave the rest as it is.

### 4. Run it once, by hand

1. Open **Hermes Chat Renderer** for editing and tap ▶︎. Run by itself, it reads Messages, and that's the only time
   iOS can ask for access to Messages. Choose **Always Allow** whenever it asks. It takes about half a minute: keep
   Shortcuts open until ■ turns back into ▶︎.
2. Then open **Hermes Lock Screen** for editing and tap ▶︎. It draws the chat on your Lock Screen.
3. Lock your iPhone: your conversation is on the Lock Screen. It fills in from your agent's next messages.

If it stops with an error, the action that failed is highlighted with a message. Take a screenshot of it.
`update-status.json` in the Hermes folder also shows where it stopped (see
[If something goes wrong](#if-something-goes-wrong)).

### 5. Set the Action button

**Settings → Action Button**, swipe to **Shortcut**, and choose **Talk to Hermes**. The first time you use it, allow
the microphone, speech recognition and Messages. Every use sends a real voice note to your agent.

### 6. Add an automation for your agent's messages

1. In Shortcuts, tap **Automation**, then **+**. If you have no automations yet, tap **Create Personal Automation**.
2. Choose **Message**. Tap **Sender**, pick your agent's contact and tap **Done**. Leave **Message Contains** empty.
3. Choose **Run Immediately** and turn off **Notify When Run**. Tap **Next**.
4. Tap **New Blank Automation**, then **Add Action**. Search for **Run Shortcut** and tap it.
5. Tap **Shortcut** in the action and choose **Hermes Lock Screen**.
6. Tap the arrow on the action, tap **Input** and choose **Shortcut Input**: the message itself, not the Sender. Tap
   **Done**.
7. If an older automation for the same contact still runs a wallpaper shortcut, delete it (swipe left on it), so only
   this one runs.

### 7. Make the wall follow the light

Each time Hermes Chat Renderer draws, it picks the wall from the Hermes folder: `wall-dawn.png`, `wall-day.png`,
`wall-dusk.png` (golden hour) or `wall.png` (moonlight). It uses the light the last Sun automation passed, or else
the hour: dawn from 5:00, daylight from 8:00, golden hour from 17:00, moonlight from 20:00. Hermes Lock Screen then
sets the drawing as your Lock Screen. On its own the wall changes only when a message arrives; these automations
redraw it when the light changes.

**With the sun (recommended).** Four automations, each passing one word:

| Trigger | Word |
|---|---|
| Sunrise, 30 minutes before | `dawn` |
| Sunrise, 1 hour after | `day` |
| Sunset, 1 hour before | `dusk` |
| Sunset, 30 minutes after | `night` |

1. Tap **Automation**, then **+**, and choose **Time of Day**.
2. Choose **Sunrise** (or **Sunset**) and the offset from the table, and keep **Repeat** on **Daily**.
3. Choose **Run Immediately** and turn off **Notify When Run**. Tap **Next**.
4. Tap **New Blank Automation**. Add a **Text** action and type the word from the table, for example `dawn`.
5. Add **Run Shortcut** under it, tap **Shortcut** and choose **Hermes Lock Screen**. It should read **Run Hermes
   Lock Screen with Text**. If it doesn't, tap the arrow on the action and set **Input** to **Text**. Tap **Done**.
6. Do the same for the other three rows.

**With fixed times (simpler).** Four automations at **5:00 AM**, **8:00 AM**, **5:00 PM** and **8:00 PM**: choose
**Time of Day**, pick the exact time, keep **Repeat** on **Daily**, choose **Run Immediately** with **Notify When Run**
off, then **New Blank Automation → Add Action → Run Shortcut → Hermes Lock Screen**, with no input.

Use one set or the other. Both only change the wall: they don't read Messages, so they're quick and work while your
iPhone is locked. If a Sun automation is missed, the wall falls back to the hour after a few hours.

### iOS 27

Automations live in the shortcut. Steps 1 to 5 are the same. Instead of steps 6 and 7:

1. Edit **Hermes Lock Screen** and tap **Automation**. Add a **Message** trigger: set **Sender** to your agent's
   contact and leave **Message Contains** empty. Then add four **Time of Day** triggers, for 5:00, 8:00, 17:00 and
   20:00, each **Daily**. A trigger here can't pass a word, so the wall follows these fixed times.
2. Still editing, tap **Info (ⓘ) → Privacy** and turn on **Allow Running When Locked**. Apple says this lets it run
   without asking or notifying you.
3. Open the **Automation** view (in Shortcuts, tap **Automation**; you may have to tap **Back** first) and check that
   the automations are on. Automations synced from another device arrive turned off. Keep them on for this iPhone
   only: two devices drawing the same chat would fight.

### Optional

- **Keep notifications off your chat**: **Settings → Notifications → Display As → Count.**
- **Give your agent a face**: put a square photo named `avatar-photo.png` in the Hermes folder.
- **Widgets under the clock**: edit Hermes Chat Renderer and raise **Top** by about 240.

## Updating from an earlier version

1. Add the new `.shortcut` files as in step 2, choosing **Replace**.
2. Do step 3 again: a replaced shortcut forgets which Lock Screen it draws on.
3. Do step 4. A run you start yourself always tries to read Messages, even while updates have paused it.

Your automations keep working. On iOS 27, check that Hermes Lock Screen still has its triggers (Edit → Automation).
To follow the sun instead of fixed times, see step 7.

## What shows

- Your agent's messages the moment they arrive, including one-word and number replies like "4.".
- Your messages, whether typed on this iPhone, your Mac or your iPad. iOS only runs automations for messages you
  receive, so yours appear when your agent reacts to one of them (that reaction also brings any you sent after it),
  or else with your agent's next message.
- Voice notes as an audio bubble straight away, with your words under the waveform once they're transcribed (from
  the Action button). Voice notes sent another way show once your agent reacts to them.
- Each message as one bubble, blank lines included, as wide as Messages would draw it. Older bubbles fade into the
  wall under the clock, so the end of a long message stays readable.
- Tapbacks (👍 ❤️ 😂, and emoji reactions) on the bubble they belong to, and messages of one to three emoji drawn
  large, as in Messages.
- "Delivered", then "Read" with the typing bubble while your agent works, and a timestamp after 15 quiet minutes.
- The wall's light following the sun, or the time of day.

## How it stays accurate

Every update does two things. First it draws the message that started it, so the Lock Screen changes at once. Then it
reads the newest messages in Messages and adds whatever the chat is missing, in the order they were sent. That covers:

- messages you sent from another device;
- replies iOS delivered late after you lost Wi-Fi or signal;
- automations iOS skipped;
- two updates that ran into each other.

Messages are matched by the moment they were sent, so nothing is added twice, and changing time zones doesn't reorder
anything. When two messages arrive together, the second update waits a few seconds for the first.

It reads only your agent's conversation: the one whose name matches what you typed in Hermes Chat Renderer. Nothing
from other conversations is saved. A new install starts empty and fills in as messages arrive: on iOS 26, Messages
doesn't say who sent the older ones.

If reading Messages ever stops partway (iOS ended it, or Messages didn't answer), each new message still shows. Updates
then skip reading Messages for 12 hours instead of failing each time. Running Hermes Lock Screen yourself tries again,
and so does any update after the 12 hours.

## If something goes wrong

**update-status.json** in the Hermes folder says what the last update did. It holds times and stages, never message
text, and `timing`: how many milliseconds it waited for another update, drew, set the wallpaper and read Messages.
`perf` in **chat.json** breaks the drawing down the same way.

| Stage | Meaning | What to do |
|---|---|---|
| `applied, synced` | Drawn from the notification, then Messages added something. | Nothing. |
| `applied, nothing new`, `… not due` | Messages had nothing to add, or was read in the last 30 seconds. | Nothing. |
| `…, busy` | Another update was reading Messages at the same time. | Nothing. |
| `…, wall` | A change of light (a Sun or Time of Day automation). | Nothing. |
| `…, paused` | A read of Messages stopped partway earlier, so updates skip reading for 12 hours. | Run Hermes Lock Screen yourself to try again. |
| `running` | Stopped while drawing. From an automation, it may also have stopped while setting the wallpaper. | Run Hermes Lock Screen from its editor and screenshot the error. |
| `running: setting the wallpaper` | Set Wallpaper failed. | Redo step 3. Check that the Lock Screen is a plain photo (step 1). |
| `running: reading Messages` | Reading Messages stopped partway. | Run it from its editor and screenshot the error. If it keeps happening, see "If updates feel slow" below. |

**The time doesn't change when a message arrives**: the automation didn't run. Check that it's turned on, and that
its input is the message (step 6).

A second file, **sync-status.json**, notes `found` each time a read by hand gets an answer from Messages. It also
appears when reading Messages found nothing of your agent's (`seen: 0`): the name typed in Hermes Chat Renderer
doesn't match the contact. Edit the first Text action in the renderer to match.

**If updates feel slow**, or reading Messages keeps stopping, edit Hermes Chat Renderer and set **ReadMessages** (near
the top) to `0`. It then draws only what notifications bring: your agent's messages and tapbacks, plus your typed
messages through those tapbacks. It no longer reads Messages.

To start a fresh chat on the Lock Screen, send `/new` to your agent.

## Limits

- Your own messages wait for your agent's next message.
- An edited message keeps the words it first had; an unsent one stays.
- The chat keeps the newest 60 bubbles.
- Reading Messages needs Messages without **Require Face ID**: a locked app's contents are kept out of search, which
  Find Messages reads through, and an automation can't ask for Face ID. With it on, set **ReadMessages** to `0`.
- Not yet verified on an iPhone: reading Messages while the iPhone is locked. On a locked Mac it works. If it fails on
  the iPhone, each message still shows from its notification, and reading pauses as described above.
- On iOS 26, Messages doesn't say who sent a message, and reading a voice note's attachment stops the shortcut. So:
  - Messages are told apart by what the chat already has. Your agent's words arrive first, from their
    notifications, so words read from Messages that aren't in the chat yet are yours. If an automation for one of
    your agent's messages never ran, that message can show on your side.
  - Messages sent before you set this up aren't added: nothing says whose they were.
  - Voice notes you send from Messages, not Talk to Hermes, show once your agent reacts to them. Your agent's photos
    show as 📎 Attachment.
- Messages reads through search, which can lag: your typed messages may show a few minutes late.

## Apple references

- iOS 26, create a personal automation:
  https://support.apple.com/guide/shortcuts/create-a-new-personal-automation-apdfbdbd7123/9.0/ios/26
- iOS 26, Time of Day and other event triggers:
  https://support.apple.com/guide/shortcuts/event-triggers-apd932ff833f/9.0/ios/26
- iOS 27, add automations, the Automation view and Allow Running When Locked:
  https://support.apple.com/guide/shortcuts/add-automations-apdfbdbd7123/10.0/ios/27
- What's new in Shortcuts for iOS 26 (Find Message, Find Conversation): https://support.apple.com/en-gb/125148
- What's new in iOS 27 (automations sync between devices): https://support.apple.com/en-tm/149045
- Notification previews and Display As: https://support.apple.com/108781
