#!/usr/bin/env python3
"""Back up your Minerva Forum classes: recordings, readings and attached files.

Talks to the same JSON API (/api/v1/...) the Forum web app uses, signed in as you
(see auth.py). Nothing is modified on Forum.

    forum-archiver              # log in, pick courses, see the download size, confirm, download
    forum-archiver --list       # just show your courses
    forum-archiver --inspect    # dump sample API responses (for debugging)
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from . import __version__, auth

BASE = "https://forum.minerva.edu"
API = BASE + "/api/v1"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".mov", ".m4v")


# --------------------------------------------------------------------------- helpers

def norm(obj):
    """Turn dashed JSON keys into snake_case recursively, so lookups work for either style."""
    if isinstance(obj, dict):
        return {(k.replace("-", "_") if isinstance(k, str) else k): norm(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [norm(v) for v in obj]
    return obj


def first(d, *keys, default=None):
    """First non-empty value among keys of d."""
    if not isinstance(d, dict):
        return default
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def as_id(v):
    if isinstance(v, dict):
        v = v.get("id")
    if isinstance(v, bool):
        return None
    if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
        return int(v)
    return None


def safe_name(s, limit=90):
    if os.name == "nt":  # stay well inside Windows' 260-character path limit
        limit = min(limit, 50)
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", str(s))
    s = re.sub(r"\s+", " ", s).strip().strip(".")
    return s[:limit].rstrip() or "untitled"


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_selection(text, n):
    text = text.strip().lower()
    if text in ("all", "a", "*"):
        return list(range(1, n + 1))
    picked = []
    for part in re.split(r"[,\s]+", text):
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            picked.extend(range(int(lo), int(hi) + 1))
        else:
            picked.append(int(part))
    bad = [i for i in picked if not 1 <= i <= n]
    if bad:
        raise ValueError(f"not in the list: {bad}")
    return list(dict.fromkeys(picked))


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def log(msg="", end="\n"):
    print(msg, end=end, file=sys.stderr, flush=True)


def status(msg):
    """Overwrite the current terminal line."""
    log(f"\r{msg}\033[K", end="")


# --------------------------------------------------------------------------- session

def make_session(cookies):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": BASE + "/app/"})
    for c in cookies:
        s.cookies.set(c["name"], c["value"], domain=c["domain"])
    s.headers["X-CSRFToken"] = next((c["value"] for c in cookies if c["name"] == "csrftoken"), "")
    return s


# --------------------------------------------------------------------------- API client

class ForumError(Exception):
    def __init__(self, status, url, body=""):
        super().__init__(f"HTTP {status} for {url}" + (f": {body[:200]}" if body else ""))
        self.status = status


class NotLoggedIn(Exception):
    pass


class Forum:
    def __init__(self, session: requests.Session, delay=0.2):
        self.s = session
        self.delay = delay
        self._courses = {}

    def _url(self, path):
        if path.startswith("http"):
            return path
        if path.startswith("/api/"):
            return BASE + path
        return API + path

    def request(self, method, path, params=None, payload=None):
        url = self._url(path)
        headers = {"Accept": "application/json; dashes=no"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json; dashes=no"
            data = json.dumps(payload)
        for attempt in range(4):
            time.sleep(self.delay)
            try:
                r = self.s.request(method, url, params=params, data=data, headers=headers,
                                   timeout=60, allow_redirects=False)
            except requests.RequestException as e:
                if attempt == 3:
                    raise ForumError(0, url, str(e))
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** (attempt + 1))
                continue
            break
        if r.status_code in (301, 302, 401) or (r.ok and "json" not in r.headers.get("Content-Type", "")):
            raise NotLoggedIn()
        if not r.ok:
            raise ForumError(r.status_code, url, r.text if r.status_code >= 500 else "")
        return norm(r.json()) if r.content else None

    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def pages(self, path, params=None):
        """Items of a list endpoint, following Django-REST style {next, results} pagination."""
        data = self.get(path, params)
        while True:
            if isinstance(data, list):
                yield from data
                return
            if not isinstance(data, dict):
                return
            yield from data.get("results") or []
            if not data.get("next"):
                return
            data = self.get(data["next"])

    # Endpoints, as used by the Forum web app.

    def me(self):
        return self.get("/users/self")

    def terms(self):
        return list(self.pages("/terms"))

    def student_sections(self, term_id=None):
        params = {"role": "student", "state": "all", "hide-defaults": "true"}
        if term_id is not None:
            params["term-id"] = term_id
        return list(self.pages("/sections", params))

    def course(self, course_id):
        if course_id not in self._courses:
            try:
                self._courses[course_id] = self.get(f"/courses/{course_id}")
            except ForumError:
                self._courses[course_id] = {}
        return self._courses[course_id]

    def past_classes(self, course_id, section_id):
        return list(self.pages(f"/courses/{course_id}/sections/{section_id}/paginated-classes",
                               {"category": "past"}))

    def class_assignments(self, class_id):
        return list(self.pages(f"/classes/{class_id}/assignments"))

    def recording_urls(self, session_id):
        # (sic) "ression" is how the endpoint is spelled on Forum.
        return self.get(f"/recording-sessions/{session_id}/generate_recording_urls_for_recording_ression")

    def resource_file_url(self, resource_id):
        data = self.get(f"/resources/{resource_id}/signed_url", {"content-disposition": "attachment"})
        return first(data, "url", "signed_url")


# --------------------------------------------------------------------------- courses

@dataclass
class Enrollment:
    section: dict
    course: dict
    term: dict

    @property
    def section_id(self):
        return as_id(self.section)

    @property
    def course_id(self):
        return as_id(self.course) or as_id(first(self.section, "course", "course_id"))

    @property
    def code(self):
        return first(self.course, "course_code", "code", default="")

    @property
    def title(self):
        return first(self.course, "title", "name", default="")

    @property
    def section_title(self):
        return first(self.section, "title", "name", default="")

    @property
    def term_name(self):
        return first(self.term, "title", "name", default="") or "Unknown term"

    @property
    def label(self):
        name = " - ".join(x for x in (self.code, self.title) if x) or f"Course {self.course_id}"
        sec = self.section_title
        return f"{name} ({sec})" if sec and sec not in name else name


def list_enrollments(forum: Forum):
    try:
        terms = sorted(forum.terms(), key=lambda t: str(first(t, "start_date", default="")))
    except ForumError as e:
        log(f"Could not list terms ({e}); falling back to current sections only.")
        terms = []
    terms_by_id = {as_id(t): t for t in terms}

    seen, out = set(), []

    def add(sections, term):
        for sec in sections:
            sid = as_id(sec)
            if sid is None or sid in seen:
                continue
            seen.add(sid)
            # Forum sends each nested object in full only once per response; repeats are {"id": ...} stubs.
            course = first(sec, "course")
            if not first(course, "title", "course_code"):
                course = forum.course(as_id(course) or as_id(first(sec, "course_id"))) or \
                    (course if isinstance(course, dict) else {})
            sec_term = first(course, "term") or first(course, "term_id") or first(sec, "term")
            if not first(sec_term, "title"):
                sec_term = terms_by_id.get(as_id(sec_term)) or term or {}
            out.append(Enrollment(sec, course, sec_term))

    for i, t in enumerate(terms, 1):
        status(f"Scanning terms {i}/{len(terms)}...")
        try:
            add(forum.student_sections(as_id(t)), t)
        except ForumError as e:
            log(f"\n  term {first(t, 'title', default=as_id(t))}: {e}")
    status("")
    if not out:
        add(forum.student_sections(), None)
    return out


def print_enrollments(enrollments):
    width = max((len(e.term_name) for e in enrollments), default=4)
    print()
    print(f"  {'#':>3}  {'Term':<{width}}  Course")
    prev = None
    for i, e in enumerate(enrollments, 1):
        term = e.term_name if e.term_name != prev else ""
        prev = e.term_name
        print(f"  {i:>3}  {term:<{width}}  {e.label}")
    print()


# --------------------------------------------------------------------------- plan: what to download and how big

@dataclass
class Recording:
    session_id: int
    dest_stem: Path          # e.g. .../recording or .../recording-2 (extension added on download)
    existing: Path | None = None
    variant: str | None = None
    size: int | None = None


@dataclass
class ClassPlan:
    summary: dict
    dir: Path
    title: str
    date: str
    recordings: list[Recording] = field(default_factory=list)


@dataclass
class CoursePlan:
    enrollment: Enrollment
    dir: Path
    classes: list[ClassPlan] = field(default_factory=list)

    @property
    def recordings(self):
        return [r for c in self.classes for r in c.recordings]


def existing_video(stem: Path):
    if not stem.parent.exists():
        return None
    return next((p for p in stem.parent.glob(stem.name + ".*")
                 if p.suffix.lower() in VIDEO_EXTS and ".part" not in p.name), None)


def plan_course(forum: Forum, e: Enrollment, out_root: Path):
    course_dir = out_root / safe_name(e.term_name) / safe_name(e.label)
    plan = CoursePlan(e, course_dir)
    classes = sorted(forum.past_classes(e.course_id, e.section_id), key=lambda c: str(first(c, "date", default="")))
    for i, c in enumerate(classes, 1):
        title = first(c, "title", "name", default=f"Class {as_id(c)}")
        date = str(first(c, "date", default=""))[:10]
        cp = ClassPlan(c, course_dir / "classes" / safe_name(f"{i:02d} {date} {title}"), title, date)
        sessions = [s for s in c.get("recording_sessions") or [] if isinstance(s, dict)
                    and s.get("recording_state") != "HIDDEN"]
        sessions.sort(key=lambda s: str(first(s, "recording_started", default="")))
        for n, s in enumerate(sessions, 1):
            stem = cp.dir / ("recording" if len(sessions) == 1 else f"recording-{n}")
            cp.recordings.append(Recording(as_id(s), stem, existing_video(stem)))
        plan.classes.append(cp)
    return plan


DL = requests.Session()
DL.headers["User-Agent"] = UA


def probe(urls):
    """(variant, url, size) of the best version we're allowed to download, or (None, None, None).
    Students usually get 403 on 'highres', so this falls back to 'lowres'."""
    for key in ("highres", "lowres"):
        url = first(urls, key)
        if not url:
            continue
        try:
            with DL.get(url, headers={"Range": "bytes=0-0"}, stream=True, timeout=30) as r:
                if r.status_code in (200, 206):
                    total = r.headers.get("Content-Range", "").rpartition("/")[2]
                    size = int(total) if total.isdigit() else int(r.headers.get("Content-Length") or 0)
                    return key, url, size or None
        except requests.RequestException:
            continue
    return None, None, None


def measure(forum: Forum, plans):
    todo = [r for p in plans for r in p.recordings if not r.existing]

    def one(rec):
        try:
            rec.variant, _, rec.size = probe(forum.recording_urls(rec.session_id))
        except (ForumError, NotLoggedIn):
            rec.variant = None

    done = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for _ in pool.map(one, todo):
            done += 1
            status(f"Checking video sizes {done}/{len(todo)}...")
    status("")


def print_plan(plans, free):
    width = min(max((len(p.enrollment.label) for p in plans), default=10), 60)
    print(f"\n  {'Course':<{width}}  {'Classes':>7}  {'Videos':>6}  {'Size':>9}")
    total = have = missing = have_bytes = 0
    for p in plans:
        recs = p.recordings
        new = [r for r in recs if not r.existing and r.variant]
        size = sum(r.size or 0 for r in new)
        total += size
        have += sum(1 for r in recs if r.existing)
        have_bytes += sum(r.existing.stat().st_size for r in recs if r.existing)
        missing += sum(1 for r in recs if not r.existing and not r.variant)
        label = p.enrollment.label
        label = label if len(label) <= width else label[:width - 1] + "…"
        print(f"  {label:<{width}}  {len(p.classes):>7}  {len(new):>6}  {human(size):>9}")
    print(f"  {'':<{width}}  {'':>7}  {'':>6}  {'─' * 9}")
    print(f"  {'Total to download':<{width}}  {'':>7}  {'':>6}  {human(total):>9}\n")
    if have:
        print(f"  Already downloaded: {have} video(s), {human(have_bytes)} (skipped)")
    if missing:
        print(f"  Not available: {missing} recording(s) Forum would not give a video for")
    print(f"  Free space: {human(free)}" + ("   ⚠ NOT ENOUGH SPACE" if total > free else ""))
    print()
    return total


# --------------------------------------------------------------------------- downloads

def download_file(url, dest: Path, label=""):
    """Stream url to dest, resuming a previous partial download if there is one."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    done = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={done}-"} if done else {}
    with DL.get(url, headers=headers, stream=True, timeout=60) as r:
        if r.status_code == 416:  # the .part file is already complete
            part.rename(dest)
            return dest
        r.raise_for_status()
        if done and r.status_code != 206:
            done = 0
        total = int(r.headers.get("Content-Length", 0)) + done
        last = 0.0
        with open(part, "ab" if done else "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if label and time.time() - last > 0.5:
                    last = time.time()
                    pct = f" {done * 100 // total}%" if total else ""
                    status(f"      {label}: {human(done)} / {human(total) if total else '?'}{pct}")
    if label:
        status(f"      {label}: {human(done)}")
        log()
    part.rename(dest)
    return dest


def url_ext(url, default=".mp4"):
    ext = Path(unquote(urlparse(url).path)).suffix.lower()
    return ext if re.fullmatch(r"\.[a-z0-9]{2,5}", ext or "") else default


def download_recording(forum: Forum, rec: Recording):
    if rec.existing:
        return rec.existing
    # Signed URLs expire, so get fresh ones right before downloading.
    try:
        urls = forum.recording_urls(rec.session_id)
    except ForumError as e:
        log(f"      {rec.dest_stem.name}: not available ({e})")
        return None
    variant, url, _ = probe(urls)
    if not url:
        log(f"      {rec.dest_stem.name}: no downloadable video")
        return None
    write_json(rec.dest_stem.with_suffix(".json"), {"recording_session": rec.session_id, "variant": variant})
    try:
        rec.existing = download_file(url, rec.dest_stem.with_suffix(url_ext(url)), rec.dest_stem.name)
    except requests.RequestException as e:
        log(f"\n      {rec.dest_stem.name}: download failed ({e}); rerun to resume")
    return rec.existing


MD_LINK = re.compile(r"\[((?:[^\[\]]|\[[^\]]*\])+)\]\((https?://[^)\s]+)\)")


def md_inline(s):
    s = html.escape(s, quote=False)
    s = MD_LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', s)
    s = re.sub(r"(?<![\"'>])(https?://[^\s<]+)", r'<a href="\1">\1</a>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"(?<!\w)\*(\S.*?)\*(?!\w)", r"<em>\1</em>", s)


def md_to_html(md):
    """Just enough Markdown for Forum's assignment descriptions: headings, lists, quotes, links."""
    out, para, in_list = [], [], False

    def flush():
        nonlocal in_list
        if para:
            out.append("<p>" + "<br>".join(md_inline(x) for x in para) + "</p>")
            para.clear()
        if in_list:
            out.append("</ul>")
            in_list = False

    for line in md.replace("​", "").splitlines():
        s = line.strip()
        if not s:
            flush()
        elif m := re.match(r"(#{1,6})\s*(.*?)\s*#*$", s):
            flush()
            out.append(f"<h{len(m[1]) + 1}>{md_inline(m[2])}</h{len(m[1]) + 1}>")
        elif m := re.match(r"[-*+]\s+(.*)", s):
            if para:
                flush()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{md_inline(m[1])}</li>")
        elif s.startswith(">"):
            flush()
            out.append(f"<blockquote>{md_inline(s.lstrip('> '))}</blockquote>")
        else:
            if in_list:
                flush()
            para.append(s)
    flush()
    return "\n".join(out)


def archive_readings(forum: Forum, cp: ClassPlan, with_files: bool):
    """readings.md/.html from the class's (pre-class) assignments, plus attached files."""
    saved = cp.dir / "assignments.json"
    if saved.exists():
        assignments = json.loads(saved.read_text(encoding="utf-8"))
    else:
        try:
            assignments = forum.class_assignments(as_id(cp.summary))
        except ForumError:
            return None
        write_json(saved, assignments)
    if not assignments:
        return None

    md = [f"# {cp.title}", ""]
    if cp.date:
        md += [f"Class date: {cp.date}", ""]
    for a in assignments:
        kind = str(first(a, "type", default="assignment")).replace("preparatory", "pre-class work")
        due = str(first(a, "due_date", default=""))[:10]
        md += [f"## {first(a, 'title', default=kind.capitalize())}" + (f" (due {due})" if due else ""), ""]
        desc = first(a, "description", default="")
        if desc:
            md += [desc.strip(), ""]
        for ar in a.get("assignment_resources") or []:
            r = first(ar, "resource") or {}
            title = first(r, "title", default=f"resource {as_id(r)}")
            url = first(r, "url")
            line = f"- Attached: [{title}]({url})" if url else f"- Attached: {title} ({first(r, 'type', default='?')})"
            if with_files and first(r, "type") == "file":
                path = download_resource(forum, r, cp.dir / "files")
                if path:
                    line = f"- Attached: [{title}](files/{path.name.replace(' ', '%20')})"
            md.append(line)
        md.append("")
    text = "\n".join(md)
    (cp.dir / "readings.md").write_text(text, encoding="utf-8")
    (cp.dir / "readings.html").write_text(PAGE.format(title=html.escape(cp.title), body=md_to_html(text.split("\n", 1)[1])),
                                          encoding="utf-8")
    return "readings.html"


def download_resource(forum: Forum, resource: dict, fdir: Path):
    rid = as_id(resource)
    name = safe_name(Path(str(first(resource, "filename", "file_name", "title", default=f"resource-{rid}"))).name, 120)
    done = [p for p in fdir.glob(f"{rid} - *") if ".part" not in p.name] if fdir.exists() else []
    if done:
        return done[0]
    try:
        url = forum.resource_file_url(rid)
    except (ForumError, NotLoggedIn):
        return None
    if not url:
        return None
    if not Path(name).suffix:
        name += url_ext(url, "")
    try:
        return download_file(url, fdir / f"{rid} - {name}")
    except requests.RequestException as e:
        log(f"      file {name}: {e}")
        return None


def archive_course(forum: Forum, plan: CoursePlan, opts):
    e = plan.enrollment
    write_json(plan.dir / "section.json", e.section)
    write_json(plan.dir / "course.json", e.course)
    entries = []
    for i, cp in enumerate(plan.classes, 1):
        log(f"    [{i}/{len(plan.classes)}] {cp.date} {cp.title}")
        write_json(cp.dir / "class.json", cp.summary)
        entry = {"n": i, "date": cp.date, "title": cp.title, "dir": cp.dir.relative_to(plan.dir).as_posix(),
                 "videos": [], "readings": None}
        if opts.readings:
            entry["readings"] = archive_readings(forum, cp, opts.files)
        if opts.videos:
            entry["videos"] = [p.name for p in map(lambda r: download_recording(forum, r), cp.recordings) if p]
        entries.append(entry)
    write_course_index(plan.dir, e, entries)


# --------------------------------------------------------------------------- offline index pages

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font:16px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;color:#222;background:#fff}}
a{{color:#1a5fb4}} table{{border-collapse:collapse;width:100%}} td,th{{padding:.4rem .6rem;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}}
blockquote{{margin:0 0 1rem;padding-left:1rem;border-left:3px solid #ccc;color:#555}}
@media (prefers-color-scheme:dark){{body{{color:#ddd;background:#1e1e1e}} a{{color:#78aeed}} td,th{{border-color:#444}} blockquote{{color:#aaa;border-color:#555}}}}
</style></head><body><h1>{title}</h1>
{body}
</body></html>"""


def link(href, text):
    return f'<a href="{html.escape(href)}">{html.escape(text)}</a>'


def write_course_index(course_dir: Path, e: Enrollment, entries):
    write_json(course_dir / "classes.json", entries)
    rows = []
    for en in entries:
        d = en["dir"]
        bits = [link(f"{d}/{v}", v) for v in en["videos"]]
        if en["readings"]:
            bits.append(link(f"{d}/{en['readings']}", "readings"))
        rows.append(f"<tr><td>{en['n']}</td><td>{html.escape(en['date'])}</td>"
                    f"<td>{link(d + '/', en['title'])}</td><td>{' · '.join(bits)}</td></tr>")
    body = (f"<p>{html.escape(e.term_name)}</p><table><tr><th>#</th><th>Date</th><th>Class</th><th></th></tr>"
            + "\n".join(rows) + "</table>")
    (course_dir / "index.html").write_text(PAGE.format(title=html.escape(e.label), body=body), encoding="utf-8")


def write_root_index(out_root: Path):
    items = []
    for idx in sorted(out_root.glob("*/*/index.html")):
        rel = idx.relative_to(out_root).as_posix()
        items.append(f"<li>{html.escape(idx.parent.parent.name)}: {link(rel, idx.parent.name)}</li>")
    body = "<ul>" + "\n".join(items) + "</ul>"
    (out_root / "index.html").write_text(PAGE.format(title="Forum archive", body=body), encoding="utf-8")


# --------------------------------------------------------------------------- inspect

def shape(obj, depth=0):
    """Structure of a JSON value with short samples, for figuring out what Forum returns."""
    if depth > 6:
        return "…"
    if isinstance(obj, dict):
        return {k: shape(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [f"{len(obj)} items"] + ([shape(obj[0], depth + 1)] if obj else [])
    if isinstance(obj, str):
        if obj.startswith("http"):
            return f"<url {url_ext(obj, '')}>"
        return obj[:60] + ("…" if len(obj) > 60 else "")
    return obj


def inspect(forum: Forum, out_root: Path):
    d = out_root / "_inspect"
    report = {}

    def grab(name, fn):
        try:
            data = fn()
        except (ForumError, NotLoggedIn) as e:
            report[name] = f"ERROR: {e}"
            log(f"  {name}: {e}")
            return None
        write_json(d / f"{name}.json", data)
        report[name] = shape(data)
        log(f"  {name}: ok")
        return data

    grab("users_self", forum.me)
    terms = grab("terms", forum.terms) or []
    sections = []
    for t in sorted(terms, key=lambda t: str(first(t, "start_date", default="")), reverse=True):
        sections = forum.student_sections(as_id(t))
        if sections:
            write_json(d / "sections.json", sections)
            report["sections"] = shape(sections)
            log(f"  sections: ok (term {as_id(t)})")
            break
    if sections:
        sec = sections[0]
        classes = grab("past_classes", lambda: forum.past_classes(as_id(sec["course"]), as_id(sec))) or []
        if classes:
            c = classes[-1]
            grab("class_assignments", lambda: forum.class_assignments(as_id(c)))
            sessions = c.get("recording_sessions") or []
            if sessions:
                grab("recording_urls", lambda: forum.recording_urls(as_id(sessions[0])))
    write_json(d / "report.json", report)
    log(f"\nWrote {d}/report.json (structure only) and the raw responses next to it.")


# --------------------------------------------------------------------------- main

LOGIN_HELP = """
Other ways to sign in:
  --browser safari|chrome|edge|brave|firefox   use the session of a browser where you're logged in to Forum
  --login-browser PATH                         use a specific Chrome/Edge/Brave for the login window
  --cookie 'sessionid=...; csrftoken=...'      cookies copied from your browser's DevTools"""


def connect(opts):
    """(forum, me) for a working session: the saved one if it's still valid, otherwise log in."""
    def try_cookies(cookies):
        if not any(c["name"] == "sessionid" for c in cookies or []):
            return None
        forum = Forum(make_session(cookies))
        try:
            return forum, forum.me()
        except (NotLoggedIn, ForumError, requests.RequestException):
            return None

    if opts.cookie:
        cookies, source = auth.parse_cookie_header(opts.cookie), "--cookie"
    else:
        saved = None if opts.login else auth.load_session()
        if saved:
            ok = try_cookies(saved)
            if ok:
                return ok
            log("Your saved Forum session has expired; logging in again.")
        try:
            if opts.browser:
                cookies, source = auth.browser_cookies(opts.browser), opts.browser
            else:
                cookies = auth.login_with_browser(lambda c: try_cookies(c) is not None, exe=opts.login_browser)
                source = "the login window"
        except auth.LoginError as e:
            sys.exit(f"Could not log in: {e}.\n{LOGIN_HELP}")
    ok = try_cookies(cookies)
    if not ok:
        hint = " Log in to forum.minerva.edu there first." if opts.browser else ""
        sys.exit(f"Forum did not accept the session from {source}.{hint}\n{LOGIN_HELP}")
    auth.save_session(cookies)
    return ok


def main():
    ap = argparse.ArgumentParser(prog="forum-archiver", description="Back up your Minerva Forum classes.")
    ap.add_argument("-o", "--out", default=str(Path.home() / "Forum Archive"),
                    help="output folder (default: ~/Forum Archive)")
    ap.add_argument("--list", action="store_true", help="list your courses and exit")
    ap.add_argument("--courses", help="courses to download without prompting, e.g. '1,3,5-7' or 'all'")
    ap.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation before downloading")
    ap.add_argument("--no-videos", dest="videos", action="store_false", help="skip class recordings")
    ap.add_argument("--no-readings", dest="readings", action="store_false", help="skip readings / assignment text")
    ap.add_argument("--no-files", dest="files", action="store_false", help="skip files attached to assignments")
    login = ap.add_argument_group("signing in (by default a browser window opens the first time)")
    login.add_argument("--login", action="store_true", help="sign in again even if a session is saved")
    login.add_argument("--logout", action="store_true", help="forget the saved session and exit")
    login.add_argument("--browser", choices=("safari", "chrome", "edge", "brave", "chromium", "firefox", "opera", "vivaldi"),
                       help="instead of the login window, use the session of a browser you're logged in with")
    login.add_argument("--login-browser", metavar="PATH", help="Chrome/Edge/Brave executable for the login window")
    login.add_argument("--cookie", default=os.environ.get("FORUM_COOKIE"), help=argparse.SUPPRESS)
    ap.add_argument("--inspect", action="store_true", help="save sample API responses for debugging")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    opts = ap.parse_args()

    if os.name == "nt":
        os.system("")  # turns on ANSI escape handling in older Windows consoles (for the progress line)

    if opts.logout:
        auth.logout()
        print("Signed out: the saved session and login-window profile are deleted.")
        return
    out_root = Path(opts.out).expanduser().resolve()
    try:
        forum, me = connect(opts)
        log(f"Signed in to Forum as {first(me, 'first_name', 'name', 'email', default='(unknown)')}")

        if opts.inspect:
            inspect(forum, out_root)
            return

        enrollments = list_enrollments(forum)
        if not enrollments:
            sys.exit("No courses found for your account.")
        print_enrollments(enrollments)
        if opts.list:
            return

        choice = opts.courses or input("Courses to download (e.g. 1,3,5-7 or 'all'): ")
        try:
            picked = [enrollments[i - 1] for i in parse_selection(choice, len(enrollments))]
        except ValueError as err:
            sys.exit(f"Invalid selection: {err}")
        if not picked:
            return

        plans = []
        for n, e in enumerate(picked, 1):
            status(f"Listing classes {n}/{len(picked)}: {e.label}")
            try:
                plans.append(plan_course(forum, e, out_root))
            except ForumError as err:
                log(f"\n  {e.label}: could not list classes ({err})")
        status("")

        out_root.mkdir(parents=True, exist_ok=True)
        if opts.videos:
            measure(forum, plans)
            total = print_plan(plans, shutil.disk_usage(out_root).free)
        else:
            total = 0
            print(f"\n  {sum(len(p.classes) for p in plans)} classes in {len(plans)} course(s); videos skipped.\n")
        if not opts.yes:
            what = "Download" + (f" {human(total)}" if opts.videos else "")
            if input(f"{what} to {out_root}? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Nothing downloaded.")
                return

        for n, plan in enumerate(plans, 1):
            log(f"\n[{n}/{len(plans)}] {plan.enrollment.term_name} · {plan.enrollment.label}")
            archive_course(forum, plan, opts)
            write_root_index(out_root)
        log(f"\nDone. Open {out_root / 'index.html'} to browse the archive.")
    except NotLoggedIn:
        sys.exit("\nForum ended the session. Run again to sign in; finished files are skipped.")
    except (KeyboardInterrupt, EOFError):
        sys.exit("\nStopped. Run the same command again to resume; finished files are skipped.")


if __name__ == "__main__":
    main()
