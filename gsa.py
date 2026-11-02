#!/usr/bin/env python3
"""Giona Social Automation: WordPress -> bozze Threads + LinkedIn (pubblicazione manuale).

Comandi principali:
  init [--queue ID ...]   crea il database e importa gli articoli esistenti come riserva
  fetch                    rileva i nuovi articoli pubblicati e li mette in coda
  next                     JSON dell'articolo da trasformare in bozze (o "niente")
  save FILE.json           salva le 5 bozze, prepara immagine, calendario e controlli
  skip ID MOTIVO           esclude un articolo dalla coda o dalla riserva
  edit POST_ID FILE.txt    corregge il testo di una bozza e la ricontrolla
  review                   bozze da riscrivere (da rivedere o bloccate)
  check                    ricontrolla tutte le bozze non pubblicate
  sheet-export             righe per il Google Sheet (JSON)
  sheet-import FILE.json   applica stati e modifiche fatte nel Google Sheet
  today                    post previsti oggi (JSON)
  calendar                 aggiorna calendario.md
  report [--week AAAA-MM-GG]  report settimanale in reports/
  status                   riepilogo rapido
"""
import argparse
import difflib
import html
import io
import json
import re
import sqlite3
import sys
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
TZ = ZoneInfo(CFG["timezone"])
UA = "GionaSocialAutomation/1.0 (+https://www.gionawebdesign.com)"
WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
POST_OPEN = ("da approvare", "approvato", "da rivedere", "bloccato")
POST_STATES = POST_OPEN + ("scartato", "pubblicato")

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  link TEXT NOT NULL,
  slug TEXT,
  date_gmt TEXT NOT NULL,
  modified_gmt TEXT,
  excerpt TEXT,
  content_text TEXT,
  categories TEXT,
  image_url TEXT,
  image_alt TEXT,
  image_local TEXT,
  stato TEXT NOT NULL CHECK (stato IN ('riserva','in_coda','programmato','escluso')),
  note TEXT,
  detected_at TEXT NOT NULL,
  week_start TEXT
);
CREATE TABLE IF NOT EXISTS posts (
  id TEXT PRIMARY KEY,
  article_id INTEGER NOT NULL REFERENCES articles(id),
  canale TEXT NOT NULL CHECK (canale IN ('threads','linkedin')),
  tipo TEXT NOT NULL,
  utm_content TEXT NOT NULL,
  testo TEXT NOT NULL,
  testo_originale TEXT NOT NULL,
  url TEXT NOT NULL,
  immagine TEXT,
  immagine_alt TEXT,
  data_prevista TEXT NOT NULL,
  stato TEXT NOT NULL CHECK (stato IN ('da approvare','approvato','da rivedere','bloccato','scartato','pubblicato')),
  problemi TEXT,
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  pubblicato_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS posts_slot ON posts(data_prevista) WHERE stato != 'scartato';
CREATE TABLE IF NOT EXISTS edits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id TEXT NOT NULL REFERENCES posts(id),
  campo TEXT NOT NULL,
  prima TEXT,
  dopo TEXT,
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  comando TEXT NOT NULL,
  esito TEXT NOT NULL
);
"""


# ---------------------------------------------------------------- utilita

def now_local():
    return datetime.now(TZ)


def iso(dt):
    return dt.isoformat(timespec="seconds")


def db():
    path = ROOT / CFG["db_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    return con


def log_run(con, comando, esito):
    con.execute("INSERT INTO runs(at, comando, esito) VALUES (?,?,?)", (iso(now_local()), comando, esito))
    con.commit()


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.geturl(), r.read(), dict(r.headers)


def out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


class _Text(HTMLParser):
    BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "blockquote", "br", "tr", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in ("h2", "h3"):
            self.parts.append("\n\n## " if tag == "h2" else "\n\n### ")
        elif tag == "li":
            self.parts.append("\n- ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(raw):
    p = _Text()
    p.feed(raw or "")
    txt = "".join(p.parts)
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n\s*\n\s*\n+", "\n\n", txt)
    return txt.strip()


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


# ---------------------------------------------------------------- WordPress

def wp_posts(per_page=100, after=None):
    page, items = 1, []
    while True:
        q = {"per_page": per_page, "page": page, "status": "publish", "orderby": "date", "order": "asc",
             "_embed": "wp:featuredmedia,wp:term"}
        if after:
            q["after"] = after
        url = f"{CFG['site']}/wp-json/wp/v2/posts?" + urllib.parse.urlencode(q)
        try:
            status, _, body, headers = http_get(url)
        except urllib.error.HTTPError as e:
            if e.code == 400 and page > 1:
                break
            raise
        batch = json.loads(body)
        items += batch
        total_pages = int(headers.get("X-WP-TotalPages", headers.get("x-wp-totalpages", "1")))
        if page >= total_pages or not batch:
            break
        page += 1
    return items


def parse_post(p):
    emb = p.get("_embedded", {})
    media = (emb.get("wp:featuredmedia") or [{}])[0] or {}
    cats = []
    for group in emb.get("wp:term", []):
        for t in group:
            if t.get("taxonomy") == "category":
                cats.append(t.get("name"))
    img_url, img_alt = media.get("source_url"), media.get("alt_text") or ""
    if not img_url and p.get("featured_media"):
        # media non esposto dalla REST API: ripiego sull'og:image della pagina pubblica
        try:
            _, _, body, _ = http_get(p["link"])
            page = body.decode("utf-8", "ignore")
            m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', page, re.I)
            img_url = html.unescape(m.group(1)) if m else None
            m = re.search(r'<meta[^>]+property=["\']og:image:alt["\'][^>]+content=["\']([^"\']+)', page, re.I)
            img_alt = html.unescape(m.group(1)) if m else ""
        except Exception:
            img_url = None
    return {
        "id": p["id"],
        "title": html.unescape(p["title"]["rendered"]),
        "link": p["link"],
        "slug": p.get("slug"),
        "date_gmt": p["date_gmt"],
        "modified_gmt": p.get("modified_gmt"),
        "excerpt": html_to_text(p.get("excerpt", {}).get("rendered", "")),
        "content_text": html_to_text(p.get("content", {}).get("rendered", "")),
        "categories": ", ".join(c for c in cats if c),
        "image_url": img_url,
        "image_alt": img_alt,
    }


def insert_article(con, a, stato):
    con.execute(
        """INSERT OR IGNORE INTO articles(id,title,link,slug,date_gmt,modified_gmt,excerpt,content_text,
           categories,image_url,image_alt,stato,detected_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (a["id"], a["title"], a["link"], a["slug"], a["date_gmt"], a["modified_gmt"], a["excerpt"],
         a["content_text"], a["categories"], a["image_url"], a["image_alt"], stato, iso(now_local())))


def cmd_init(args):
    con = db()
    if con.execute("SELECT COUNT(*) FROM articles").fetchone()[0]:
        sys.exit("Database gia inizializzato.")
    posts = [parse_post(p) for p in wp_posts()]
    queue = set(args.queue or [])
    for a in posts:
        insert_article(con, a, "in_coda" if a["id"] in queue else "riserva")
    con.commit()
    log_run(con, "init", f"{len(posts)} articoli, in coda: {sorted(queue)}")
    out({"articoli": len(posts), "in_coda": sorted(queue)})


def cmd_fetch(args):
    con = db()
    known = {r[0] for r in con.execute("SELECT id FROM articles")}
    last = con.execute("SELECT MAX(date_gmt) FROM articles").fetchone()[0]
    after = None
    if last:
        after = (datetime.fromisoformat(last) - timedelta(days=14)).isoformat()
    new = []
    for p in wp_posts(after=after):
        if p.get("status") != "publish" or p["id"] in known:
            continue
        a = parse_post(p)
        insert_article(con, a, "in_coda")
        new.append({"id": a["id"], "title": a["title"], "date_gmt": a["date_gmt"]})
    con.commit()
    log_run(con, "fetch", f"nuovi: {[n['id'] for n in new]}")
    out({"nuovi": new})


# ---------------------------------------------------------------- calendario

def slot_datetimes(tuesday):
    res = []
    for s in CFG["slots"]:
        d = tuesday + timedelta(days=s["weekday"] - 1)
        hh, mm = map(int, s["time"].split(":"))
        res.append((s, datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ)))
    return res


def week_taken(con, tuesday):
    return con.execute("SELECT 1 FROM articles WHERE week_start = ? AND stato = 'programmato'",
                       (tuesday.isoformat(),)).fetchone() is not None


def first_free_week(con, ref=None):
    ref = ref or now_local()
    d = ref.date() + timedelta(days=(1 - ref.weekday()) % 7)
    while True:
        first = slot_datetimes(d)[0][1]
        if first > ref and not week_taken(con, d):
            return d
        d += timedelta(days=7)


def cmd_next(args):
    con = db()
    row = con.execute("SELECT * FROM articles WHERE stato = 'in_coda' ORDER BY date_gmt ASC LIMIT 1").fetchone()
    reserve = False
    week = first_free_week(con)
    if not row:
        # riserva evergreen solo se la prossima settimana libera inizia entro 48 ore
        start = slot_datetimes(week)[0][1]
        if start - now_local() <= timedelta(hours=48):
            cutoff = (now_local() - timedelta(days=CFG["limits"]["reserve_cooldown_days"])).isoformat()
            row = con.execute(
                """SELECT a.* FROM articles a WHERE a.stato = 'riserva' AND NOT EXISTS (
                     SELECT 1 FROM posts p WHERE p.article_id = a.id AND p.created_at > ?)
                   ORDER BY a.date_gmt ASC LIMIT 1""", (cutoff,)).fetchone()
            reserve = row is not None
    if not row:
        out({"articolo": None, "motivo": "nessun articolo in coda e settimana successiva gia coperta o lontana"})
        return
    recent = [r["testo"] for r in con.execute(
        "SELECT testo FROM posts WHERE stato != 'scartato' ORDER BY created_at DESC LIMIT 30")]
    openings = [t.strip().split("\n")[0][:120] for t in recent]
    out({
        "articolo": {k: row[k] for k in ("id", "title", "link", "date_gmt", "categories", "excerpt",
                                          "image_url", "image_alt", "content_text")},
        "riserva_evergreen": reserve,
        "settimana": week.isoformat(),
        "calendario": [{"data": iso(dt), "giorno": WEEKDAYS[dt.weekday()], "canale": s["canale"], "tipo": s["tipo"],
                        "immagine": s["immagine"]} for s, dt in slot_datetimes(week)],
        "aperture_recenti_da_non_ripetere": openings,
        "pagine_del_sito_utilizzabili": site_pages(),
        "istruzioni": "Scrivi le 5 bozze seguendo linee-guida.md e salvale con: python3 gsa.py save bozze.json",
    })


def site_pages():
    pages = []
    try:
        _, _, body, _ = http_get(f"{CFG['site']}/wp-json/wp/v2/pages?per_page=100&_fields=link,title,status")
        for p in json.loads(body):
            if p.get("status") == "publish":
                pages.append({"titolo": html.unescape(p["title"]["rendered"]), "url": p["link"]})
    except Exception:
        pass
    return pages


# ---------------------------------------------------------------- UTM e link

def utm_url(base, canale, tipo):
    parts = urllib.parse.urlsplit(base)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if not k.startswith("utm_")]
    q += [("utm_source", canale), ("utm_medium", "social"), ("utm_campaign", CFG["utm_campaign"]),
          ("utm_content", f"{canale}_{tipo}")]
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(q), ""))


def check_link(url, expected_canonical=None):
    """Ritorna lista di problemi (vuota se ok)."""
    probs = []
    host = urllib.parse.urlsplit(url).netloc
    if host not in ("www.gionawebdesign.com", "gionawebdesign.com"):
        return [f"link fuori dal sito: {url}"]
    try:
        status, final, body, _ = http_get(url)
    except Exception as e:
        return [f"link non raggiungibile ({e}): {url}"]
    if status != 200:
        probs.append(f"link risponde {status}: {url}")
    page = body.decode("utf-8", "ignore")
    if re.search(r'<meta[^>]+name=["\']robots["\'][^>]+noindex', page, re.I):
        probs.append(f"pagina in noindex: {url}")
    if expected_canonical:
        m = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', page, re.I)
        if m and m.group(1).rstrip("/") != expected_canonical.rstrip("/"):
            probs.append(f"canonical diverso: {m.group(1)}")
    return probs


# ---------------------------------------------------------------- immagini

def prepare_image(con, art):
    """Copia JPEG dell'immagine in evidenza. Non tocca l'originale su WordPress."""
    from PIL import Image, ImageCms  # noqa: F401
    if not art["image_url"]:
        return None, ["articolo senza immagine in evidenza"]
    try:
        status, _, raw, headers = http_get(art["image_url"])
    except Exception as e:
        return None, [f"immagine non accessibile pubblicamente ({e})"]
    if status != 200:
        return None, [f"immagine risponde {status}"]
    img = Image.open(io.BytesIO(raw))
    if img.mode not in ("RGB", "L"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
        img = bg
    img = img.convert("RGB")
    lim = CFG["limits"]
    if img.width > lim["image_max_width"]:
        h = round(img.height * lim["image_max_width"] / img.width)
        img = img.resize((lim["image_max_width"], h), Image.LANCZOS)
    folder = ROOT / CFG["images_dir"] / str(art["id"])
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{art['slug'] or art['id']}.jpg"
    img.save(path, "JPEG", quality=90, optimize=True, progressive=True)
    rel = str(path.relative_to(ROOT))
    con.execute("UPDATE articles SET image_local = ? WHERE id = ?", (rel, art["id"]))
    return rel, image_problems(rel)


def image_problems(rel):
    from PIL import Image
    probs = []
    p = ROOT / rel
    if not p.exists():
        return [f"immagine mancante: {rel}"]
    lim = CFG["limits"]
    if p.stat().st_size > lim["image_max_bytes"]:
        probs.append("immagine oltre 8 MB")
    with Image.open(p) as im:
        if im.format != "JPEG":
            probs.append("immagine non JPEG")
        if im.width < lim["image_min_width"]:
            probs.append(f"immagine troppo stretta ({im.width}px)")
        ratio = max(im.width / im.height, im.height / im.width)
        if ratio > 10:
            probs.append("proporzioni oltre 10:1")
    return probs


# ---------------------------------------------------------------- controlli testo

EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF⭐⭕‼⁉]")


def text_problems(post, art_text, siblings, history):
    t = post["testo"]
    probs = []
    lim = CFG["limits"]
    if post["url"] not in t:
        probs.append("link mancante nel testo")
    n = len(t)
    if post["canale"] == "threads" and n > lim["threads_max_chars"]:
        probs.append(f"Threads: {n} caratteri, limite {lim['threads_max_chars']}")
    if post["canale"] == "linkedin":
        if n > lim["linkedin_max_chars"]:
            probs.append(f"LinkedIn: {n} caratteri, limite {lim['linkedin_max_chars']}")
        if n < lim["linkedin_min_chars"]:
            probs.append(f"LinkedIn: solo {n} caratteri, troppo breve")
    if "—" in t:
        probs.append("contiene il trattino lungo")
    if EMOJI.search(t):
        probs.append("contiene emoji")
    low = t.lower()
    for b in CFG["banned_phrases"]:
        if b in low:
            probs.append(f"formula vietata: \"{b}\"")
    if re.search(r"\{[a-z_]*\}|\*\*|^#{1,6} |\[[^\]]+\]\(", t, re.M):
        probs.append("formattazione residua (segnaposto o markdown)")
    if re.search(r"  |\n\n\n", t):
        probs.append("spazi o righe vuote doppie")
    # numeri: ogni numero citato deve comparire nell'articolo
    body = t.replace(post["url"], "")
    art_digits = re.sub(r"\s", "", art_text)
    for num in set(re.findall(r"\d+(?:[.,]\d+)?", body)):
        if num not in art_digits:
            probs.append(f"numero non presente nell'articolo: {num}")
    # duplicati
    plain = norm(body)
    for sid, stxt in siblings:
        r = difflib.SequenceMatcher(None, plain, norm(stxt)).ratio()
        if r > lim["max_similarity"]:
            probs.append(f"troppo simile a {sid} ({r:.2f})")
    opening = norm(t.split("\n")[0])[:80]
    for hid, htxt in history:
        if opening and norm(htxt.split("\n")[0])[:80] == opening:
            probs.append(f"apertura gia usata in {hid}")
    return probs


def run_checks(con, post_ids=None):
    q = "SELECT * FROM posts WHERE stato IN ('da approvare','approvato','da rivedere','bloccato')"
    rows = con.execute(q).fetchall()
    report = {}
    link_cache = {}
    for p in rows:
        if post_ids and p["id"] not in post_ids:
            continue
        art = con.execute("SELECT * FROM articles WHERE id = ?", (p["article_id"],)).fetchone()
        sib = [(s["id"], s["testo"].replace(s["url"], "")) for s in rows
               if s["article_id"] == p["article_id"] and s["id"] != p["id"]]
        hist = [(h["id"], h["testo"]) for h in con.execute(
            "SELECT id, testo FROM posts WHERE article_id != ? AND stato != 'scartato'", (p["article_id"],))]
        probs = text_problems(dict(p), art["content_text"] + " " + art["title"], sib, hist)
        base = p["url"].split("?")[0]
        if base not in link_cache:
            link_cache[base] = check_link(p["url"], art["link"] if base == art["link"] else None)
        probs += link_cache[base]
        slot = next(s for s in CFG["slots"] if s["canale"] == p["canale"] and s["tipo"] == p["tipo"])
        if slot["immagine"]:
            if p["immagine"]:
                probs += image_problems(p["immagine"])
            else:
                probs.append("immagine prevista ma non disponibile: pubblicare come post testuale")
        day = p["data_prevista"][:10]
        same_day = con.execute("SELECT COUNT(*) FROM posts WHERE substr(data_prevista,1,10) = ? AND stato != 'scartato'",
                               (day,)).fetchone()[0]
        if same_day > 1:
            probs.append("piu di un post nello stesso giorno")
        hard = [x for x in probs if not x.startswith("immagine prevista")]
        new_state = p["stato"]
        if hard and p["stato"] in ("da approvare", "approvato"):
            new_state = "bloccato"
        elif not hard and p["stato"] == "bloccato":
            new_state = "da approvare"
        con.execute("UPDATE posts SET problemi = ?, stato = ?, updated_at = ? WHERE id = ?",
                    ("; ".join(probs), new_state, iso(now_local()), p["id"]))
        report[p["id"]] = {"stato": new_state, "problemi": probs}
    con.commit()
    return report


# ---------------------------------------------------------------- salvataggio bozze

def cmd_save(args):
    con = db()
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    art = con.execute("SELECT * FROM articles WHERE id = ?", (data["article_id"],)).fetchone()
    if not art:
        sys.exit(f"Articolo {data['article_id']} non presente nel database.")
    if art["stato"] not in ("in_coda", "riserva"):
        sys.exit(f"Articolo {art['id']} in stato {art['stato']}: bozze gia create.")
    wanted = {(s["canale"], s["tipo"]) for s in CFG["slots"]}
    got = {(p["canale"], p["tipo"]) for p in data["posts"]}
    if wanted != got or len(data["posts"]) != len(wanted):
        sys.exit(f"Servono esattamente questi post: {sorted(wanted)}")
    week = date.fromisoformat(args.week) if args.week else first_free_week(con)
    if week_taken(con, week):
        sys.exit(f"Settimana {week} gia occupata.")
    img_rel, img_probs = prepare_image(con, art)
    slots = {(s["canale"], s["tipo"]): (s, dt) for s, dt in slot_datetimes(week)}
    ts = iso(now_local())
    ids = []
    for p in data["posts"]:
        s, dt = slots[(p["canale"], p["tipo"])]
        base = p.get("url_base") or art["link"]
        url = utm_url(base, p["canale"], p["tipo"])
        if "{link}" not in p["testo"]:
            sys.exit(f"Manca il segnaposto {{link}} nel post {p['canale']}/{p['tipo']}")
        testo = p["testo"].strip().replace("{link}", url)
        pid = f"{art['id']}-{p['canale']}-{p['tipo']}"
        con.execute(
            """INSERT INTO posts(id,article_id,canale,tipo,utm_content,testo,testo_originale,url,immagine,
               immagine_alt,data_prevista,stato,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, art["id"], p["canale"], p["tipo"], f"{p['canale']}_{p['tipo']}", testo, testo, url,
             img_rel if s["immagine"] and not img_probs else None, art["image_alt"] if s["immagine"] else None,
             iso(dt), "da approvare", ts, ts))
        ids.append(pid)
    con.execute("UPDATE articles SET stato = 'programmato', week_start = ? WHERE id = ?", (week.isoformat(), art["id"]))
    con.commit()
    res = run_checks(con, set(ids))
    write_calendar(con)
    log_run(con, "save", f"articolo {art['id']} settimana {week}: " +
            ", ".join(f"{k}={v['stato']}" for k, v in res.items()))
    out({"articolo": art["id"], "settimana": week.isoformat(), "immagine": img_rel,
         "problemi_immagine": img_probs, "post": res})


def cmd_skip(args):
    con = db()
    con.execute("UPDATE articles SET stato = 'escluso', note = ? WHERE id = ?", (args.motivo, args.id))
    con.commit()
    log_run(con, "skip", f"{args.id}: {args.motivo}")
    out({"escluso": args.id})


def cmd_edit(args):
    """Corregge il testo di una bozza non pubblicata. Il segnaposto {link} viene sostituito con l'URL tracciato."""
    con = db()
    p = con.execute("SELECT * FROM posts WHERE id = ?", (args.id,)).fetchone()
    if not p or p["stato"] in ("pubblicato", "scartato"):
        sys.exit(f"Bozza {args.id} inesistente o non modificabile.")
    testo = Path(args.file).read_text(encoding="utf-8").strip().replace("{link}", p["url"])
    ts = iso(now_local())
    con.execute("INSERT INTO edits(post_id,campo,prima,dopo,at) VALUES (?,?,?,?,?)",
                (p["id"], "testo", p["testo"], testo, ts))
    stato = "da approvare" if p["stato"] in ("da rivedere", "bloccato") else p["stato"]
    if stato != p["stato"]:
        con.execute("INSERT INTO edits(post_id,campo,prima,dopo,at) VALUES (?,?,?,?,?)",
                    (p["id"], "stato", p["stato"], stato, ts))
    con.execute("UPDATE posts SET testo = ?, stato = ?, updated_at = ? WHERE id = ?", (testo, stato, ts, p["id"]))
    con.commit()
    res = run_checks(con, {p["id"]})
    write_calendar(con)
    log_run(con, "edit", f"{p['id']}: {res[p['id']]['stato']}")
    out(res)


def cmd_review(args):
    """Bozze da riscrivere: stato 'da rivedere' (con la nota dell'utente) o 'bloccato' (con i problemi)."""
    con = db()
    rows = con.execute("""SELECT p.*, a.title, a.link, a.content_text FROM posts p JOIN articles a ON a.id = p.article_id
                          WHERE p.stato IN ('da rivedere','bloccato') ORDER BY p.data_prevista""").fetchall()
    out([{"id": r["id"], "stato": r["stato"], "canale": r["canale"], "tipo": r["tipo"], "data": r["data_prevista"],
          "nota_utente": r["note"], "problemi": r["problemi"], "testo_attuale": r["testo"].replace(r["url"], "{link}"),
          "articolo": r["title"], "testo_articolo": r["content_text"]} for r in rows])


def cmd_check(args):
    con = db()
    out(run_checks(con))


# ---------------------------------------------------------------- Google Sheet

SHEET_HEADER = ["ID", "Data", "Giorno", "Ora", "Canale", "Tipo", "Articolo", "Testo", "Caratteri",
                "Link tracciato", "Immagine", "Stato", "Problemi", "Note"]
REPO_BLOB = "https://github.com/GGionata/giona-social-automation/blob/main/"


def cmd_sheet_export(args):
    con = db()
    # finestra mobile: ultimi 14 giorni, tutto il futuro e ogni bozza ancora aperta
    since = (now_local().date() - timedelta(days=14)).isoformat()
    rows = [SHEET_HEADER]
    for p in con.execute("""SELECT p.*, a.title FROM posts p JOIN articles a ON a.id = p.article_id
                            WHERE substr(p.data_prevista,1,10) >= ? OR p.stato IN ('da approvare','da rivedere','bloccato')
                            ORDER BY p.data_prevista DESC""", (since,)):
        dt = datetime.fromisoformat(p["data_prevista"])
        rows.append([p["id"], dt.strftime("%Y-%m-%d"), WEEKDAYS[dt.weekday()], dt.strftime("%H:%M"),
                     "Threads" if p["canale"] == "threads" else "LinkedIn", p["tipo"], p["title"], p["testo"],
                     len(p["testo"]), p["url"], REPO_BLOB + p["immagine"] if p["immagine"] else "",
                     p["stato"], p["problemi"] or "", p["note"] or ""])
    out(rows)


def same_text(a, b):
    """Ignora differenze di trascrizione (spazi, apostrofi tipografici, normalizzazione unicode)."""
    def n(s):
        s = unicodedata.normalize("NFC", s or "")
        s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
        return re.sub(r"\s+", " ", s).strip()
    return n(a) == n(b)


def cmd_sheet_import(args):
    """Applica dal foglio: Stato, Testo e Note. Il foglio vince solo dove l'utente ha cambiato qualcosa."""
    con = db()
    rows = json.loads(Path(args.file).read_text(encoding="utf-8"))
    if rows and rows[0] and rows[0][0] == "ID":
        header, rows = rows[0], rows[1:]
    else:
        header = SHEET_HEADER
    ix = {h: i for i, h in enumerate(header)}
    changed, retest = [], set()
    ts = iso(now_local())
    for r in rows:
        r = list(r) + [""] * (len(header) - len(r))
        pid = r[ix["ID"]]
        p = con.execute("SELECT * FROM posts WHERE id = ?", (pid,)).fetchone()
        if not p:
            continue
        stato = (r[ix["Stato"]] or "").strip().lower()
        testo = (r[ix["Testo"]] or "").replace("\r\n", "\n").strip()
        nota = (r[ix["Note"]] or "").strip()
        if testo and same_text(testo, p["testo"]):
            testo = p["testo"]
        if testo and testo != p["testo"]:
            con.execute("INSERT INTO edits(post_id,campo,prima,dopo,at) VALUES (?,?,?,?,?)",
                        (pid, "testo", p["testo"], testo, ts))
            url = p["url"]
            found = re.findall(r"https://(?:www\.)?gionawebdesign\.com/\S+", testo)
            if found and found[0] != url:
                url = found[0]
            con.execute("UPDATE posts SET testo = ?, url = ?, updated_at = ? WHERE id = ?", (testo, url, ts, pid))
            changed.append(f"{pid}: testo modificato")
            retest.add(pid)
        if stato and stato != p["stato"]:
            if stato not in POST_STATES:
                changed.append(f"{pid}: stato '{stato}' non valido, ignorato")
            elif stato == "approvato" and p["stato"] == "bloccato" and pid not in retest:
                changed.append(f"{pid}: non approvabile finche restano problemi")
            else:
                con.execute("INSERT INTO edits(post_id,campo,prima,dopo,at) VALUES (?,?,?,?,?)",
                            (pid, "stato", p["stato"], stato, ts))
                extra = ", pubblicato_at = ?" if stato == "pubblicato" else ""
                params = [stato, ts] + ([ts] if extra else []) + [pid]
                con.execute(f"UPDATE posts SET stato = ?, updated_at = ?{extra} WHERE id = ?", params)
                changed.append(f"{pid}: {p['stato']} -> {stato}")
        if nota != (p["note"] or ""):
            con.execute("UPDATE posts SET note = ? WHERE id = ?", (nota, pid))
    con.commit()
    res = run_checks(con, retest) if retest else {}
    write_calendar(con)
    log_run(con, "sheet-import", "; ".join(changed) or "nessuna modifica")
    out({"modifiche": changed, "ricontrolli": res})


# ---------------------------------------------------------------- oggi, calendario, report

def cmd_today(args):
    con = db()
    d = args.date or now_local().date().isoformat()
    rows = con.execute("""SELECT p.*, a.title FROM posts p JOIN articles a ON a.id = p.article_id
                          WHERE substr(p.data_prevista,1,10) = ? AND p.stato != 'scartato'""", (d,)).fetchall()
    out([{"id": r["id"], "ora": r["data_prevista"][11:16], "canale": r["canale"], "tipo": r["tipo"],
          "stato": r["stato"], "testo": r["testo"], "immagine": REPO_BLOB + r["immagine"] if r["immagine"] else None,
          "alt": r["immagine_alt"], "problemi": r["problemi"]} for r in rows])


def write_calendar(con):
    lines = ["# Calendario editoriale", "",
             f"Aggiornato: {now_local().strftime('%Y-%m-%d %H:%M')} ({CFG['timezone']})", "",
             "| Data | Ora | Canale | Tipo | Articolo | Stato | Problemi |", "|---|---|---|---|---|---|---|"]
    for p in con.execute("""SELECT p.*, a.title FROM posts p JOIN articles a ON a.id = p.article_id
                            ORDER BY p.data_prevista DESC LIMIT 60"""):
        dt = datetime.fromisoformat(p["data_prevista"])
        lines.append(f"| {WEEKDAYS[dt.weekday()]} {dt:%d/%m/%Y} | {dt:%H:%M} | {p['canale']} | {p['tipo']} | "
                     f"{p['title']} | {p['stato']} | {(p['problemi'] or '').replace('|', '/')} |")
    q = con.execute("SELECT id, title FROM articles WHERE stato = 'in_coda' ORDER BY date_gmt").fetchall()
    lines += ["", "## Articoli in coda", ""] + ([f"- {r['id']}: {r['title']}" for r in q] or ["- nessuno"])
    (ROOT / "calendario.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_calendar(args):
    con = db()
    write_calendar(con)
    print("calendario.md aggiornato")


def cmd_report(args):
    con = db()
    ref = date.fromisoformat(args.week) if args.week else now_local().date()
    tuesday = ref - timedelta(days=(ref.weekday() - 1) % 7)
    end = tuesday + timedelta(days=6)
    posts = con.execute("""SELECT p.*, a.title, a.link FROM posts p JOIN articles a ON a.id = p.article_id
                           WHERE substr(p.data_prevista,1,10) BETWEEN ? AND ? ORDER BY p.data_prevista""",
                        (tuesday.isoformat(), end.isoformat())).fetchall()
    arts = {}
    for p in posts:
        arts.setdefault((p["article_id"], p["title"], p["link"]), []).append(p)
    lines = [f"# Report settimana {tuesday:%d/%m/%Y} - {end:%d/%m/%Y}", ""]
    if not posts:
        lines.append("Nessun post previsto in questa settimana.")
    for (aid, title, link), ps in arts.items():
        lines += [f"## Articolo: {title}", "", f"Fonte: {link}", ""]
        for p in ps:
            dt = datetime.fromisoformat(p["data_prevista"])
            lines += [f"### {p['canale'].capitalize()} {p['tipo']} ({WEEKDAYS[dt.weekday()]} {dt:%d/%m %H:%M})", "",
                      f"Stato: {p['stato']}" + (f" | Problemi: {p['problemi']}" if p["problemi"] else ""), "",
                      f"Link: {p['url']}", "", f"Immagine: {p['immagine'] or 'nessuna'}", "", "```text", p["testo"],
                      "```", ""]
    counts = {}
    for p in posts:
        counts[p["stato"]] = counts.get(p["stato"], 0) + 1
    edits = con.execute("SELECT COUNT(*) FROM edits WHERE at >= ?", (tuesday.isoformat(),)).fetchone()[0]
    q = con.execute("SELECT COUNT(*) FROM articles WHERE stato = 'in_coda'").fetchone()[0]
    lines += ["## Riepilogo", "", f"- Post previsti: {len(posts)}",
              "- Per stato: " + (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "nessuno"),
              f"- Modifiche manuali registrate: {edits}", f"- Articoli in coda: {q}",
              "- Traffico GA4: da collegare (utm_source threads/linkedin, utm_campaign blog_articolo)"]
    folder = ROOT / CFG["reports_dir"]
    folder.mkdir(exist_ok=True)
    path = folder / f"{tuesday.isoformat()}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(str(path.relative_to(ROOT)))


def cmd_status(args):
    con = db()
    out({
        "articoli": dict(con.execute("SELECT stato, COUNT(*) FROM articles GROUP BY stato").fetchall()),
        "post": dict(con.execute("SELECT stato, COUNT(*) FROM posts GROUP BY stato").fetchall()),
        "prossima_settimana_libera": first_free_week(con).isoformat(),
        "ultime_esecuzioni": [dict(r) for r in con.execute("SELECT at, comando, esito FROM runs ORDER BY id DESC LIMIT 5")],
    })


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init"); s.add_argument("--queue", type=int, nargs="*"); s.set_defaults(f=cmd_init)
    sub.add_parser("fetch").set_defaults(f=cmd_fetch)
    sub.add_parser("next").set_defaults(f=cmd_next)
    s = sub.add_parser("save"); s.add_argument("file"); s.add_argument("--week"); s.set_defaults(f=cmd_save)
    s = sub.add_parser("skip"); s.add_argument("id", type=int); s.add_argument("motivo"); s.set_defaults(f=cmd_skip)
    s = sub.add_parser("edit"); s.add_argument("id"); s.add_argument("file"); s.set_defaults(f=cmd_edit)
    sub.add_parser("review").set_defaults(f=cmd_review)
    sub.add_parser("check").set_defaults(f=cmd_check)
    sub.add_parser("sheet-export").set_defaults(f=cmd_sheet_export)
    s = sub.add_parser("sheet-import"); s.add_argument("file"); s.set_defaults(f=cmd_sheet_import)
    s = sub.add_parser("today"); s.add_argument("--date"); s.set_defaults(f=cmd_today)
    sub.add_parser("calendar").set_defaults(f=cmd_calendar)
    s = sub.add_parser("report"); s.add_argument("--week"); s.set_defaults(f=cmd_report)
    sub.add_parser("status").set_defaults(f=cmd_status)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
