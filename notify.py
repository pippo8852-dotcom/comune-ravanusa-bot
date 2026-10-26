"""Avvisi Telegram per le Novità del Comune di Ravanusa (feed RSS del sito)."""
import os
import json
import re
import html
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
import requests

# Configurazione Telegram
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

STATE_FILE = "sent_items.json"
SEND_DELAY = 3           # secondi di pausa tra due messaggi (Telegram: circa 20 al minuto per chat)
MAX_SEND_ATTEMPTS = 3    # tentativi per ogni messaggio quando Telegram risponde 429
MAX_RETRY_WAIT = 60      # attesa massima accettata per un nuovo tentativo, in secondi

SITE_URL = "https://www.comune.ravanusa.ag.it"
FEED_URL = f"{SITE_URL}/feed/"
# Indirizzi alternativi dello stesso feed WordPress, provati in ordine se il primo non risponde.
FEED_URLS = [
    FEED_URL,
    f"{SITE_URL}/?feed=rss2",
    f"{SITE_URL}/feed/atom/",
]
# Alternativa più leggera del feed: l'API di WordPress (stesso sito, stessi contenuti).
WP_API_URL = f"{SITE_URL}/wp-json/wp/v2/posts?per_page=10&_fields=id,link,title,date_gmt"
FEED_TIMEOUT = 20        # secondi di attesa massima per ogni richiesta
FEED_ATTEMPTS = 2        # tentativi per ogni indirizzo
FEED_RETRY_WAIT = 5      # secondi di attesa tra due tentativi
FEED_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}
ATOM_NS = "{http://www.w3.org/2005/Atom}"

LOCAL_TZ_NAME = "Europe/Rome"


def format_local(dt):
    """Formatta una data come gg/mm/aaaa HH:MM, convertita all'ora italiana se ha il fuso."""
    if dt.tzinfo is not None:
        try:
            dt = dt.astimezone(ZoneInfo(LOCAL_TZ_NAME))
        except Exception:
            pass
    return dt.strftime("%d/%m/%Y %H:%M")


def parse_feed_date(text):
    """Legge la data di un feed (RSS: RFC 822, Atom: ISO 8601). None se assente o illeggibile."""
    if not text or not text.strip():
        return None
    text = text.strip()
    try:
        return format_local(parsedate_to_datetime(text))
    except (TypeError, ValueError):
        pass
    try:
        return format_local(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def parse_wp_gmt_date(text):
    """Data 'date_gmt' dell'API WordPress (ISO senza fuso, in UTC). None se assente o illeggibile."""
    if not text or not str(text).strip():
        return None
    try:
        dt = datetime.fromisoformat(str(text).strip())
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return format_local(dt)


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"Errore nel salvataggio dello stato: {e}")


def _retry_after(resp):
    """Secondi di attesa richiesti da Telegram dopo un 429 (None se non indicati)."""
    try:
        value = resp.json().get("parameters", {}).get("retry_after")
        if value is not None:
            return float(value)
    except Exception:
        pass
    try:
        return float(resp.headers.get("Retry-After"))
    except (TypeError, ValueError):
        return None


def send_telegram_message(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Token o Chat ID mancanti nei Secrets.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 429 and attempt < MAX_SEND_ATTEMPTS:
                wait = (_retry_after(response) or 5) + 1
                if wait <= MAX_RETRY_WAIT:
                    print(f"⏳ Telegram chiede di rallentare (429): attendo {wait:.0f}s e riprovo "
                          f"({attempt}/{MAX_SEND_ATTEMPTS})")
                    time.sleep(wait)
                    continue
            response.raise_for_status()
            print("✅ Messaggio Telegram inviato!")
            return True
        except Exception as e:
            print(f"❌ Errore invio Telegram: {e}")
            return False
    return False


def _clean_title(text):
    title = " ".join((text or "").split())
    if not title:
        return "Nuova notizia"
    return title[:197] + "..." if len(title) > 200 else title


def _child(entry, *tags):
    """Primo figlio dell'elemento con uno dei tag indicati (None se assente)."""
    for tag in tags:
        node = entry.find(tag)
        if node is not None:
            return node
    return None


def _entry_link(entry):
    """Link di una voce RSS (<link>testo</link>) o Atom (<link href=... />)."""
    for node in entry.findall("link") + entry.findall(f"{ATOM_NS}link"):
        if node.get("href") and node.get("rel", "alternate") == "alternate":
            return node.get("href").strip()
        if node.text and node.text.strip():
            return node.text.strip()
    return None


def _parse_feed_xml(resp):
    """Notizie di un feed RSS 2.0 o Atom."""
    root = ET.fromstring(resp.content)
    entries = root.findall(".//item") or root.findall(f".//{ATOM_NS}entry")
    unique_items = {}
    for entry in entries:
        link = _entry_link(entry)
        if not link:
            continue

        id_node = _child(entry, "guid", f"{ATOM_NS}id")
        item_id = (id_node.text or "").strip() if id_node is not None else ""
        item_id = item_id or link

        title_node = _child(entry, "title", f"{ATOM_NS}title")
        title = _clean_title(title_node.text if title_node is not None else "")

        date_node = _child(entry, "pubDate", f"{ATOM_NS}published", f"{ATOM_NS}updated")
        date = parse_feed_date(date_node.text) if date_node is not None else None

        category_nodes = entry.findall("category")
        categoria = category_nodes[0].text.strip() if category_nodes and category_nodes[0].text else None

        if item_id not in unique_items:
            unique_items[item_id] = {"id": item_id, "title": title, "link": link,
                                     "date": date, "subject": categoria}

    print(f"📋 Notizie uniche nel feed: {len(unique_items)}")
    return list(unique_items.values())


def _parse_wp_posts(resp):
    """Notizie dall'API REST di WordPress. Gli ID hanno lo stesso formato dei guid del feed
    (https://sito/?p=123), così non si creano duplicati passando da una fonte all'altra."""
    posts = resp.json()
    if not isinstance(posts, list):
        raise ValueError(f"risposta API inattesa: {str(posts)[:100]}")
    unique_items = {}
    for post in posts:
        post_id, link = post.get("id"), post.get("link")
        if not post_id or not link:
            continue
        raw_title = (post.get("title") or {}).get("rendered", "")
        title = _clean_title(html.unescape(re.sub(r"<[^>]+>", "", raw_title)))
        item_id = f"{SITE_URL}/?p={post_id}"
        if item_id not in unique_items:
            unique_items[item_id] = {"id": item_id, "title": title, "link": link,
                                     "date": parse_wp_gmt_date(post.get("date_gmt"))}
    print(f"📋 Notizie uniche dall'API WordPress: {len(unique_items)}")
    return list(unique_items.values())


def _fetch_with_retries(url, parse):
    """Scarica un indirizzo e ne interpreta la risposta con parse(resp), con qualche nuovo
    tentativo. Restituisce la lista di notizie oppure None se non riesce."""
    for attempt in range(1, FEED_ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers=FEED_HEADERS, timeout=FEED_TIMEOUT)
            print(f"📡 Status HTTP feed ({url}): {resp.status_code}")
            resp.raise_for_status()
            return parse(resp)
        except Exception as e:
            print(f"❌ Errore durante la lettura del feed (tentativo {attempt}/{FEED_ATTEMPTS}): {e}")
            if attempt < FEED_ATTEMPTS:
                time.sleep(FEED_RETRY_WAIT)
    return None


def fetch_novita():
    """Prova in ordine: feed principale, API WordPress, poi gli altri indirizzi del feed."""
    attempts = [(FEED_URLS[0], _parse_feed_xml), (WP_API_URL, _parse_wp_posts)]
    attempts += [(url, _parse_feed_xml) for url in FEED_URLS[1:]]
    for url, parse in attempts:
        items = _fetch_with_retries(url, parse)
        if items is not None:
            return items
    return []


# --- Sezione "Novità" del sito -------------------------------------------------------------
# Il feed principale (/feed/) contiene solo gli articoli "classici" e si ferma a novembre 2025,
# mentre le notizie più recenti stanno nella sezione /novita/ (un tipo di contenuto a parte).
NOVITA_PREFIX = f"{SITE_URL}/novita/"
NOVITA_FEED_URL = f"{NOVITA_PREFIX}feed/"
REST_BASE = f"{SITE_URL}/wp-json/wp/v2"
# Tipi di contenuto standard di WordPress: non sono la sezione Novità
TIPI_STANDARD = {"post", "page", "attachment", "nav_menu_item", "wp_block", "wp_template",
                 "wp_template_part", "wp_navigation", "wp_font_family", "wp_font_face",
                 "wp_global_styles"}


def _solo_novita(items):
    """Tiene solo le voci della sezione Novità e usa il link come ID: è uguale sia che la
    notizia arrivi dal feed sia che arrivi dall'API, quindi non si creano duplicati."""
    risultato = {}
    for item in items:
        if item["link"].startswith(NOVITA_PREFIX):
            risultato.setdefault(item["link"], dict(item, id=item["link"]))
    return list(risultato.values())


def _parse_novita_feed(resp):
    return _solo_novita(_parse_feed_xml(resp))


def _parse_novita_rest(resp):
    return _solo_novita(_parse_wp_posts(resp))


def _parse_tipi_di_contenuto(resp):
    """Percorsi REST dei tipi di contenuto personalizzati (tutti tranne quelli standard)."""
    tipi = resp.json()
    if not isinstance(tipi, dict):
        raise ValueError(f"risposta API inattesa: {str(tipi)[:100]}")
    return [info.get("rest_base") or slug for slug, info in tipi.items()
            if slug not in TIPI_STANDARD and isinstance(info, dict)]


def _data_di(item):
    try:
        return datetime.strptime(item.get("date"), "%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return None


def _fetch_novita_rest():
    """Cerca da sola il tipo di contenuto che ospita le Novità: elenca i tipi personalizzati,
    legge le ultime voci di ciascuno e tiene quelle con link /novita/."""
    percorsi = _fetch_with_retries(f"{REST_BASE}/types", _parse_tipi_di_contenuto)
    if percorsi is None:
        return None
    print(f"🔎 Tipi di contenuto personalizzati trovati: {percorsi}")
    trovate = {}
    for percorso in percorsi:
        url = f"{REST_BASE}/{percorso}?per_page=10&_fields=id,link,title,date_gmt"
        for item in _fetch_with_retries(url, _parse_novita_rest) or []:
            trovate.setdefault(item["id"], item)
    return sorted(trovate.values(), key=lambda i: _data_di(i) or datetime.min, reverse=True)


def fetch_novita_sezione():
    """Notizie della sezione Novità: prima il feed della sezione, poi l'API di WordPress."""
    items = _fetch_with_retries(NOVITA_FEED_URL, _parse_novita_feed)
    if items:
        return items
    print("ℹ️ Feed della sezione Novità non disponibile o vuoto: provo con l'API di WordPress.")
    return _fetch_novita_rest() or []


def _piu_vecchia_di(item, giorni):
    """True se la notizia ha una data e risale a più di `giorni` giorni fa."""
    data = _data_di(item)
    if data is None:
        return False
    try:
        adesso = datetime.now(ZoneInfo(LOCAL_TZ_NAME)).replace(tzinfo=None)
    except Exception:
        adesso = datetime.now()
    return (adesso - data).days > giorni


# Ogni fonte ha: chiave nello stato, etichetta del messaggio, funzione di lettura
# e "enabled" (se False la fonte viene saltata del tutto: nessuna richiesta, nessun invio).
SOURCES = [
    {"key": "feed_ravanusa", "label": "📰 Novità Comune di Ravanusa",
     "link_label": "🔗 Leggi la notizia",
     "fetch": lambda: fetch_novita(), "enabled": True},
    # Sezione Novità del sito (notizie recenti). max_age_days: ignora le notizie più vecchie di così,
    # per evitare di rimandare notizie vecchie se una fonte restituisse un elenco non aggiornato.
    {"key": "novita_ravanusa", "label": "📰 Novità Comune di Ravanusa",
     "link_label": "🔗 Leggi la notizia",
     "fetch": lambda: fetch_novita_sezione(), "enabled": True, "max_age_days": 60},
]


def process_source(state, source):
    key = source["key"]
    state.setdefault(key, [])
    known_ids = set(state[key])
    items = source["fetch"]()

    new_items = [item for item in items if item["id"] not in known_ids]
    max_age = source.get("max_age_days")
    if max_age:
        recenti = [item for item in new_items if not _piu_vecchia_di(item, max_age)]
        if len(recenti) < len(new_items):
            print(f"🕓 Ignorate {len(new_items) - len(recenti)} notizie più vecchie di {max_age} giorni.")
        new_items = recenti
    print(f"📊 Summary [{source['label']}]: Letti {len(items)} | Nuovi da inviare {len(new_items)}")
    print(f"🗓 Date trovate: {sum(1 for i in items if i.get('date'))} su {len(items)}")

    for n, item in enumerate(reversed(new_items)):
        if n > 0:
            time.sleep(SEND_DELAY)  # rispetta il limite di Telegram sui messaggi al minuto
        # Titolo e link vanno "escapati": con parse_mode HTML un carattere come & o <
        # farebbe rifiutare il messaggio da Telegram.
        title = html.escape(item["title"], quote=False)
        link = html.escape(item["link"], quote=True)
        date_line = f"🗓 {html.escape(item['date'])}\n" if item.get("date") else ""
        body = title
        if item.get("subject"):
            body += "\n" + html.escape(item["subject"], quote=False)
        link_label = html.escape(source.get("link_label", "🔗 Apri"), quote=False)
        msg = f"<b>{source['label']}</b>\n{date_line}\n{body}\n\n<a href='{link}'>{link_label}</a>"
        if send_telegram_message(msg):
            state[key].append(item["id"])
        else:
            # Invio fallito: non segniamo la notizia come inviata, così verrà
            # ritentata alla prossima esecuzione. Ci fermiamo per mantenere l'ordine.
            print(f"⚠️ Invio fallito per la notizia {item['id']}: riproverò alla prossima esecuzione.")
            break


def main():
    state = load_state()
    for source in SOURCES:
        if not source.get("enabled", True):
            continue
        process_source(state, source)
    save_state(state)


if __name__ == "__main__":
    main()
