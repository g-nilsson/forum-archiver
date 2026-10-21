# Forum Archiver

Save your Minerva classes before you lose access to Forum.

Forum Archiver downloads, for the courses you choose:

- 🎥 **Class recordings** as regular `.mp4` files you can play in any video player
- 📖 **Pre-class work**: the study guide, readings and links for every session (as Markdown and HTML)
- 📎 **Files attached** to the pre-class assignments

It also builds a small offline website (`index.html`) to browse everything by term, course and
class.

It signs in as you and reads only what Forum already shows you. It never changes anything on
Forum.

---

## Quick start (Mac)

You need about 5 minutes and, ideally, **Google Chrome** (Edge or Brave also work; Safari-only?
[see below](#only-have-safari-or-firefox)).

### 1. Get access and download the code

This repository is private. Ask the owner to add your GitHub account as a collaborator, then:

1. On this page, click the green **Code** button → **Download ZIP**.
2. Double-click the ZIP in your Downloads folder to unzip it.

### 2. Install uv (one time)

[uv](https://docs.astral.sh/uv/) runs Python programs and sets up Python for you. Open the
**Terminal** app (⌘ + Space, type "Terminal") and paste:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then **close Terminal and open it again**.

### 3. Run it

In Terminal, go into the unzipped folder and start the archiver:

```sh
cd ~/Downloads/forum-archiver-main
uv run forum-archiver
```

The first run takes a few seconds longer while uv sets things up.

### 4. Follow the steps

**Sign in.** A Chrome window opens on the Forum login page. Sign in like you normally would
(e.g. "Sign in with Google"). As soon as you're in, the window closes by itself and the
archiver continues. Your login is remembered, so next time this step is skipped.

**Pick your courses.** You'll see every course you took, grouped by term:

```
    #  Term         Course
   20  Fall 2022    CS111 - Single and Multivariable Calculus (…)
   21               CS110 - Problem Solving with Data Structures and Algorithms (…)
   22               SS110 - Psychology: From Neurons to Society (…)
   …
Courses to download (e.g. 1,3,5-7 or 'all'):
```

Type the numbers you want, e.g. `20-22`, `4,5,21`, or `all`, and press Enter.

**Check the size before anything downloads.** It checks every recording and tells you how much
space you need versus how much you have:

```
  Course                                        Classes  Videos       Size
  CS110 - Problem Solving with Data Structur…        25      25     7.0 GB
                                                                 ─────────
  Total to download                                                 7.0 GB

  Free space: 459.1 GB
Download 7.0 GB to /Users/you/Forum Archive? [y/N]
```

Type `y` to start, or just press Enter to cancel.

**Browse your archive.** When it's done, open **`Forum Archive/index.html`** in your home folder.

---

## Good to know

- **How much space?** About 250–350 MB per class, so roughly **7 GB per course**. A whole degree
  is around 100–150 GB, so an external drive helps (see `-o` below).
- **Video quality.** Forum only lets students download its "lowres" version. It's still
  1080p, just more compressed, and looks fine for watching classes.
- **Interrupted?** Closed your laptop, or lost Wi-Fi? Run the same command again. Finished
  videos are skipped and half-finished ones continue where they stopped.
- **Logged out?** If Forum ends your session, the next run opens the login window again.
- **Privacy.** Recordings show your classmates and professors. Keep your archive to yourself
  and don't upload or share the videos.

## Options

Add these after `uv run forum-archiver`:

| Option | What it does |
|---|---|
| `-o /Volumes/MyDrive/Minerva` | Save somewhere else, e.g. an external drive (default: `~/Forum Archive`) |
| `--list` | Only show your courses, download nothing |
| `--courses 20-27` | Choose courses without being asked |
| `-y` | Don't ask for confirmation (useful with `--courses`) |
| `--no-videos` | Skip videos and only save readings and files (fast, a few MB) |
| `--no-readings`, `--no-files` | Skip readings or attached files |
| `--login` | Sign in again, e.g. with a different account |
| `--logout` | Forget your saved login |

Example: save the readings for every course, then videos for two courses on an external
drive:

```sh
uv run forum-archiver --no-videos --courses all -y
uv run forum-archiver --courses 21,30 -o "/Volumes/MyDrive/Forum Archive"
```

## Only have Safari (or Firefox)?

The automatic login window needs Chrome, Edge or Brave, because Safari can't be controlled
this way. The easiest fix is to install [Chrome](https://www.google.com/chrome/). You can
keep using Safari for everything else.

Otherwise you can borrow the login from your normal browser:

- **Safari**
  1. Log in to [forum.minerva.edu](https://forum.minerva.edu) in Safari.
  2. Give Terminal permission to read Safari's data: **System Settings → Privacy & Security →
     Full Disk Access** → turn on **Terminal** (restart Terminal afterwards).
  3. Run `uv run --extra browser-cookies forum-archiver --browser safari`.
- **Firefox**: log in to Forum in Firefox, then run `uv run forum-archiver --browser firefox`.

## What you get

```
Forum Archive/
├── index.html                                ← start here
└── Fall 2022/
    └── CS110 - Problem Solving with Data Structures and Algorithms (…)/
        ├── index.html                        ← every class with its links
        └── classes/
            ├── 01 2022-09-05 CS110 Session 1 - …/
            │   ├── recording.mp4
            │   ├── readings.md               ← study guide, readings, links (Markdown)
            │   ├── readings.html             ← same, for the browser
            │   ├── files/                    ← attachments, if any
            │   └── class.json, assignments.json   (raw data from Forum)
            └── 02 …
```

`readings.md` files drop straight into note apps like Obsidian or Notion.

**Not included:** your answers in the interactive pre-class workbooks (PCW). Those live in a
separate Minerva app that this tool can't export yet.

## Troubleshooting

| Problem | Fix |
|---|---|
| `command not found: uv` | Close and reopen Terminal after installing uv. |
| `no such file or directory` after `cd` | The folder name may differ. Type `cd ` (with a space), drag the unzipped folder onto the Terminal window, and press Enter. |
| "no Chrome, Edge, Brave or Chromium found" | Install Chrome, or see [Only have Safari](#only-have-safari-or-firefox). |
| "the login browser exited right away" | A login window from an earlier run is still open. Close it and run again. |
| Sign-in loops or fails | Run `uv run forum-archiver --logout`, then try again. |
| A course shows 0 videos | That course had no recordings on Forum (e.g. study groups, office hours). |
| `NOT ENOUGH SPACE` | Pick fewer courses, free up space, or save to an external drive with `-o`. |

## For developers

The archiver talks to the same undocumented JSON API that the Forum web app uses
(`https://forum.minerva.edu/api/v1/...`), with your session cookie:

| Data | Endpoint |
|---|---|
| Account / terms | `GET /users/self`, `GET /terms` |
| Your sections | `GET /sections?role=student&state=all&term-id=…` |
| Past classes (incl. recording sessions) | `GET /courses/{course}/sections/{section}/paginated-classes?category=past` |
| Pre-class assignment & readings | `GET /classes/{class}/assignments` |
| Video URLs (signed, expire quickly) | `GET /recording-sessions/{id}/generate_recording_urls_for_recording_ression` |
| Attached files | `GET /resources/{id}/signed_url?content-disposition=attachment` |

Login (`forum_archiver/auth.py`) opens a Chromium-based browser with a separate profile and
`--remote-debugging-port`, waits for you to sign in, and reads the session cookie over the
Chrome DevTools Protocol. It uses a tiny built-in WebSocket client, so the only dependency is
`requests`. The session is saved (readable only by you) in
`~/Library/Application Support/forum-archiver/` on macOS, `~/.config/forum-archiver/` on Linux,
or `%APPDATA%\forum-archiver\` on Windows.

Run from a checkout with `uv run forum-archiver` or `python3 -m forum_archiver`. If Forum
changes its API, `--inspect` saves sample responses to `<output>/_inspect/` to see what
changed.
