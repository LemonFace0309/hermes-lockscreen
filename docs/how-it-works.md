# How it works

## The three shortcuts

| Shortcut | Job |
|---|---|
| **Hermes Lock Screen** | What your automations run. It takes turns with other updates, runs the renderer, and sets the Lock Screen (never the Home Screen). |
| **Hermes Chat Renderer** | Keeps the chat and draws the picture. Replacing it is how the design gets updated. |
| **Talk to Hermes** | For the Action button. It records a voice note, sends it, transcribes it, then runs Hermes Lock Screen with your words. |

Everything lives in **iCloud Drive › Shortcuts › Hermes**:
- the images;
- `chat.json`, the chat;
- `rows/`, one picture per bubble;
- `update-status.json`, what the last update did.

## One update, step by step

1. A message from your agent fires the Message automation, which runs Hermes Lock Screen with the message.
2. Hermes Lock Screen reads `update-status.json`. If another update is running, it waits its turn, so two messages
   that arrive together can't overwrite each other.
3. **First pass.** The renderer adds the message, draws its bubble, and stacks the bubbles. It fades the top under
   the clock and lays everything on the wall picture for the time of day. Hermes Lock Screen sets the result as the
   Lock Screen.
4. **Second pass, when due** (after your agent reacts to something you sent, or at most every 30 seconds). The
   renderer reads the newest messages in Messages and adds what's missing: your own messages, and anything iOS
   skipped. If that changed the chat, the Lock Screen is set again.

## The chat file

- `chat.json` keeps one record per bubble: who sent it, when, what kind (text or voice note), its reaction, its size
  on screen, and its words.
- Records are matched by the moment the message was sent, so nothing is added twice. Changing time zones doesn't
  reorder anything.
- A record added from a notification gets a temporary key. When the message is read from Messages, it gets its
  confirmed key and time.

## Drawing fast enough

Shortcuts is slow at pictures. Measured on an iPhone 16 Pro:

| Step | Time |
|---|---|
| a plain action | about 2.5 ms |
| reading a small file | about 20 ms |
| an image step (crop, mask, overlay, combine, text) | 30–140 ms |
| saving a drawn image | about 0.5 s |

Automations run in the background, roughly 3.5× slower than that, probably because background work doesn't get the
GPU.

So the renderer does as little picture work as it can:
- **Each bubble is drawn once**, when it arrives, and saved in `rows/`.
- **Older bubbles are kept stacked** in `rows/col.png`. The newest few stay outside it and are folded in every third
  update, so the big stack is saved only now and then.
- **The final picture** is one overlay on the wall.
- **Blank canvases and gaps** come from small ready-made images instead of being cut from a large one.

`perf` in `chat.json` and `timing` in `update-status.json` say how long each part of the last update took.

## Reading Messages on iOS 26

The renderer uses the **Find Messages** action. On iOS 26:
- **It reads through the search index**, which can lag behind by minutes or more. Your typed messages may show late.
- **Reading a voice note's attachments ends the shortcut.** So attachments are never read. A message with no words
  that isn't a reaction is skipped. Your voice notes come straight from Talk to Hermes instead.
- **The Sender is always empty.** So the renderer works it out:
  - Words that match a notification already in the chat are your agent's.
  - Status lines like "⏳ Working" are your agent's.
  - A reaction belongs to whoever didn't write the bubble it's on.
  - Anything else is yours.
  - Messages from before the chat began are left out, since nothing says whose they are.
- **A reaction to a voice note tells when that voice note was sent.** That's how voice notes get placed in order.
- **iOS asks for access to Messages only when the renderer runs by itself**, which is why setup runs it once by hand.

If a read stops partway, every message still shows from its notification. Updates skip reading for 12 hours, and a
run by hand tries again.

## Building and testing

- `tools/build_shortcut.py` generates all three shortcuts. `design/tokens.json` holds every size, color and timing.
  `tools/render_assets.swift` draws the images from `design/plates/`, the wall photos.
- `tools/sim.mjs` runs the generated shortcuts on a simulated iPhone that acts like iOS 26.
  `tools/test_scenarios.mjs` has 77 situations it must handle; `python3 tools/test_scenarios.py` runs them.
- `tools/package.sh` builds `Hermes.zip`. `tools/build.sh` does the same build, then copies the result to your own
  iCloud Drive for testing.
- To find what breaks on a real iPhone, build one of these, add it, run it, and read its file from iCloud Drive:
  - `tools/build_read_probe.py` reads Messages one property at a time;
  - `tools/build_speed_test.py` times each kind of step.
