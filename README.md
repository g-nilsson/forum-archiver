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

## Quick info

- **Privacy.** Since recordings show your classmates and professors, please don't publicly upload or share the videos without everyone's consent. I take no responsibility for legal consequences if that is done using this tool.
- **How much space?** About 250–350 MB per class, so roughly **7 GB per course**. The whole degree
  is around 100–150 GB, so an external drive might help (see `-o` below).
- **Video quality.** Forum only lets me download its "lowres" version (which is better anyway to don't use too much storage).
- **Interrupted?** Closed your laptop, or lost Wi-Fi? Run the same command again. Finished
  videos should be skipped and half-finished ones continue where they stopped.
- **Logged out?** If Forum ends your session, the next run opens the login window again.

---

## Quick start (Mac & Windows)

You need a Chromium-based browser for signing in: **Google Chrome**, **Microsoft
Edge** or **Brave**. Mac with only Safari?
[See below](#only-have-safari-or-firefox).

### 1. Download the code

1. On this page, click the green **Code** button → **Download ZIP**.
2. Unzip it:
   - **Mac:** double-click the ZIP in your Downloads folder.
   - **Windows:** right-click the ZIP in your Downloads folder → **Extract All…** → **Extract**.

### 2. Install uv (one time)

[uv](https://docs.astral.sh/uv/) runs Python programs and sets up Python for you.

**Mac:** open the **Terminal** app (⌘ + Space, type "Terminal") and paste:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows:** open **PowerShell** (Start menu, type "PowerShell") and paste:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then **close the Terminal / PowerShell window and open a new one**, so it finds `uv`.

### 3. Run it

Go into the unzipped folder and start the archiver.

**Mac** (Terminal):

```sh
cd ~/Downloads/forum-archiver-main
uv run forum-archiver
```

**Windows** (PowerShell). "Extract All" puts the files in a folder inside a folder of the same
name:

```powershell
cd $HOME\Downloads\forum-archiver-main\forum-archiver-main
uv run forum-archiver
```

The first run takes a few seconds longer while uv sets things up.

### 4. Follow the steps

**Sign in.** A browser window (Chrome, Edge or Brave) opens on the Forum login page. Sign in
like you normally would (e.g. "Sign in with Google"). As soon as you're in, the window closes
by itself and the archiver continues. Your login is remembered, so next time this step is
skipped.

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

**Browse your archive.** When it's done, open **`Forum Archive/index.html`** in your home folder
(`/Users/<you>` on Mac, `C:\Users\<you>` on Windows).

---

## Options

Add any of these after `uv run forum-archiver`. They work the same on Mac and Windows:

| Option | What it does |
|---|---|
| `-o <folder>` | Save somewhere else, e.g. an external drive (default: `Forum Archive` in your home folder) |
| `--list` | Only show your courses, download nothing |
| `--courses 20-27` | Choose courses without being asked |
| `-y` | Don't ask for confirmation (useful with `--courses`) |
| `--no-videos` | Skip videos and only save readings and files (fast, a few MB) |
| `--no-readings`, `--no-files` | Skip readings or attached files |
| `--login` | Sign in again, e.g. with a different account |
| `--logout` | Forget your saved login |

Example: save the readings for every course, then videos for two courses on an external drive:

```sh
uv run forum-archiver --no-videos --courses all -y
uv run forum-archiver --courses 21,30 -o "<drive>/Forum Archive"
```

Replace `<drive>` with where your drive is mounted: something like `/Volumes/MyDrive` on a Mac,
or `E:` on Windows. Put the folder in quotes if it contains spaces.

## Only have Safari (or Firefox)?

The automatic login window needs Chrome, Edge or Brave, because Safari can't be controlled
this way. The easiest fix is to install [Chrome](https://www.google.com/chrome/). (On
Windows, Edge is always there, so this doesn't apply.)

Otherwise you can borrow the login from your normal browser:

- **Safari** (Mac)
  1. Log in to [forum.minerva.edu](https://forum.minerva.edu) in Safari.
  2. Give Terminal permission to read Safari's data: **System Settings → Privacy & Security →
     Full Disk Access** → turn on **Terminal** (restart Terminal afterwards).
  3. Run `uv run --extra browser-cookies forum-archiver --browser safari`.
- **Firefox** (Mac or Windows): log in to Forum in Firefox, then run
  `uv run forum-archiver --browser firefox`.

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

On Windows, long course and class names are shortened to stay within Windows' path-length limit.

**Not included:** your answers in the interactive pre-class workbooks (PCW). Those live in a
separate Minerva app that this tool doesn't have access to.

## Troubleshooting

| Problem | Fix |
|---|---|
| `command not found: uv` (Mac) / `uv is not recognized` (Windows) | Close and reopen Terminal / PowerShell after installing uv. |
| Windows: "running scripts is disabled on this system" when installing uv | Copy the install command exactly as shown; it starts with `powershell -ExecutionPolicy ByPass`. |
| `cd` says the folder doesn't exist | The folder name may differ. Type `cd ` (with a space), drag the folder that contains `README.md` onto the window, and press Enter. |
| `No such file or directory: pyproject.toml` / "no `project` table found" | You're one folder too high (common on Windows). `cd` into the inner `forum-archiver-main` folder. |
| "no Chrome, Edge, Brave or Chromium found" | Install Chrome, or see [Only have Safari](#only-have-safari-or-firefox). |
| "the login browser exited right away" | A login window from an earlier run is still open. Close it and run again. |
| Sign-in loops or fails | Run `uv run forum-archiver --logout`, then try again. |
| A course shows 0 videos | That course had no recordings on Forum (e.g. study groups, office hours). |
| `NOT ENOUGH SPACE` | Pick fewer courses, free up space, or save to an external drive with `-o`. |

## Reporting problems

Something not working, or not covered in [Troubleshooting](#troubleshooting)?
[Open an issue](https://github.com/g-nilsson/forum-archiver/issues/new/choose) and fill in the
short form. Please include:

- Mac or Windows, and which version
- which browser you signed in with
- the exact command you ran
- the error message, copied as text
- the output of `uv run forum-archiver --version`

> ⚠️ **Issues are public.** Never paste your `session.json`, cookies, anything from your
> browser's DevTools, or other personal information.

No GitHub account, or the problem involves something private? Message me directly instead.

## License

[MIT](LICENSE)
