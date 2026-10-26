"""Avvisi Telegram: Novità del Comune di Ravanusa, lette dalla pagina /novita/ del sito
   (il feed del sito è fermo a novembre 2025, quindi si legge direttamente la pagina).
   Stessa impostazione del bot UST Milano: pagina HTML letta con una ricerca nel testo,
   stato salvato su file, comunicazioni troppo vecchie ignorate."""
import html
import json
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")        # es. @nomecanale oppure -100123...
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")   # facoltativa: se manca la pagina si legge direttamente

STATO = Path("sent_items.json")
NOME_FONTE = "📰 Novità Comune di Ravanusa"

SITE_URL = "https://www.comune.ravanusa.ag.it"
URL = f"{SITE_URL}/novita/"
SCRAPERAPI_ENDPOINT = "https://api.scraperapi.com"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

GIORNI_MASSIMI = 30          # ignora notizie più vecchie di così
INVIA_AL_PRIMO_GIRO = True   # True: al primo avvio invia le notizie entro GIORNI_MASSIMI; False: parte in silenzio
PAUSA_TRA_MESSAGGI = 3       # secondi (Telegram: circa 20 messaggi al minuto per chat)
TENTATIVI_INVIO = 3
ATTESA_MASSIMA = 60          # secondi: se Telegram chiede di aspettare di più, si rimanda alla prossima corsa

# Il sito scrive il mese con tre lettere (OTT, SET...): basta guardare le prime tre
MESI = {"gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
        "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12}

# Titolo di una notizia: un link a /novita/<nome>/ dentro un titolo (h1-h6)
TITOLO = re.compile(
    r'<h[1-6][^>]*>\s*(?:<[^>/][^>]*>\s*)*<a\b[^>]*?href="((?:https?://www\.comune\.ravanusa\.ag\.it)?'
    r'/novita/[^"#?/]+/?)"[^>]*>([\s\S]*?)</a>',
    re.IGNORECASE,
)
# Data della scheda: "08 OTT 26" o "26 OTT 2026" (anche con spazi non separabili), da sola dentro un
# elemento oppure preceduta da poche parole (es. "AVVISI - 26 OTT 2026"). Le date scritte dentro i
# testi lunghi (descrizioni) non contano.
DATA = re.compile(
    r'>\s*[^<>\d]{0,25}?(\d{1,2})(?:\s|&nbsp;)+([A-Za-zÀ-ú]{3,9})\.?(?:\s|&nbsp;)+(\d{2,4})\s*<')
# Categoria: link alla categoria della notizia (Avvisi, Notizie, Comunicati...)
CATEGORIA = re.compile(
    r'<a\b[^>]*href="[^"]*/categoria-notizia/[^"]*"[^>]*>([\s\S]*?)</a>', re.IGNORECASE)
FINESTRA_INTESTAZIONE = 1200   # caratteri prima del titolo in cui cercare data e categoria


def oggi():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Rome")).date()
    except Exception:
        return date.today()


def _testo(frammento):
    """Toglie i tag HTML e normalizza spazi e codici (&amp;, &#8217;...)."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", frammento)).split())


def _data_da(frammento_html):
    """Ultima data valida della scheda (HTML sopra il titolo) come oggetto date; None se non c'è."""
    trovata = None
    for giorno, mese, anno in DATA.findall(frammento_html):
        n_mese = MESI.get(mese.lower()[:3])
        if not n_mese:
            continue
        anno = int(anno)
        if anno < 100:
            anno += 2000
        try:
            trovata = date(anno, n_mese, int(giorno))
        except ValueError:
            continue
    return trovata


def estrai_voci(pagina):
    """Notizie della pagina, nell'ordine in cui compaiono: (link, titolo, data, categoria)."""
    voci = {}
    fine_precedente = 0
    for m in TITOLO.finditer(pagina):
        link = urljoin(SITE_URL, m.group(1).strip())
        titolo = _testo(m.group(2))
        # data e categoria stanno sopra il titolo, dopo la notizia precedente
        inizio = max(fine_precedente, m.start() - FINESTRA_INTESTAZIONE)
        sopra = pagina[inizio:m.start()]
        data = _data_da(sopra)
        categorie = CATEGORIA.findall(sopra)
        categoria = _testo(categorie[-1]) if categorie else None
        fine_precedente = m.end()
        if titolo and link not in voci:      # le notizie "in evidenza" ripetono link già visti
            voci[link] = (link, titolo, data, categoria or None)
    return list(voci.values())


def leggi():
    if SCRAPERAPI_KEY:
        resp = requests.get(SCRAPERAPI_ENDPOINT, params={"api_key": SCRAPERAPI_KEY, "url": URL}, timeout=60)
        print(f"📡 Status HTTP Novità Ravanusa (via ScraperAPI): {resp.status_code}")
    else:
        resp = requests.get(URL, headers=HEADERS, timeout=30)
        print(f"📡 Status HTTP Novità Ravanusa: {resp.status_code}")
    resp.raise_for_status()

    voci = estrai_voci(resp.text)
    if not voci:
        # aiuto per capire se il sito ha cambiato struttura
        punto = resp.text.find("/novita/")
        brano = resp.text[max(0, punto - 150):punto + 350] if punto >= 0 else resp.text[:300]
        print(f"🧪 Nessuna notizia riconosciuta. Brano della pagina: {brano!r}")
    return voci


def formatta_messaggio(titolo, data, link, categoria=None):
    """Messaggio in HTML di Telegram: la scritta "Leggi la notizia" è il link stesso.
    Titolo e link vanno "escapati", altrimenti & o < farebbero rifiutare il messaggio."""
    intestazione = html.escape(NOME_FONTE, quote=False)
    if categoria:
        intestazione += f" - {html.escape(categoria, quote=False)}"
    righe = [intestazione, html.escape(titolo, quote=False)]
    if data:
        righe.append(f"📅 {data.strftime('%d/%m/%Y')}")
    righe.append(f'<a href="{html.escape(link, quote=True)}">🔗 Leggi la notizia</a>')
    return "\n".join(righe)


def invia(testo):
    """Invia un messaggio. True se è partito, False se non è stato possibile
    (in quel caso la notizia verrà ritentata alla prossima corsa)."""
    if not TOKEN or not CHAT_ID:
        print("❌ Token o Chat ID mancanti nei Secrets.")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    dati = {"chat_id": CHAT_ID, "text": testo, "parse_mode": "HTML",
            "disable_web_page_preview": "true"}
    for tentativo in range(1, TENTATIVI_INVIO + 1):
        try:
            r = requests.post(url, data=dati, timeout=20)
            if r.status_code == 429 and tentativo < TENTATIVI_INVIO:
                try:
                    attesa = float(r.json().get("parameters", {}).get("retry_after", 5)) + 1
                except Exception:
                    attesa = 6
                if attesa <= ATTESA_MASSIMA:
                    print(f"⏳ Telegram: troppe richieste, aspetto {attesa:.0f}s (tentativo {tentativo}/{TENTATIVI_INVIO})")
                    time.sleep(attesa)
                    continue
            r.raise_for_status()
            print("✅ Messaggio Telegram inviato!")
            return True
        except Exception as e:
            print(f"❌ Errore invio Telegram: {e}")
            return False
    return False


def carica_stato():
    if STATO.exists():
        try:
            return json.loads(STATO.read_text())
        except Exception:
            return {}
    return {}


def salva_stato(stato):
    try:
        STATO.write_text(json.dumps(stato, ensure_ascii=False, indent=1))
    except Exception as e:
        print(f"Errore nel salvataggio dello stato: {e}")


def main():
    stato = carica_stato()
    adesso = oggi()

    try:
        voci = leggi()
    except Exception as e:
        print(f"[{NOME_FONTE}] errore: {e}")
        salva_stato(stato)
        return
    if not voci:
        print(f"[{NOME_FONTE}] nessun elemento letto: controlla se il layout è cambiato")
        salva_stato(stato)
        return

    visti = set(stato.get(NOME_FONTE, {}).get("visti", []))
    primo_giro = NOME_FONTE not in stato
    nuove = [v for v in voci if v[0] not in visti]
    recenti = [v for v in nuove if v[2] is None or (adesso - v[2]).days <= GIORNI_MASSIMI]
    troppo_vecchie = [v for v in nuove if v not in recenti]

    nuovi_visti = set(visti) | {v[0] for v in troppo_vecchie}
    if primo_giro and not INVIA_AL_PRIMO_GIRO:
        da_inviare = []
        nuovi_visti |= {v[0] for v in recenti}      # parte in silenzio: segna tutto come già visto
    else:
        da_inviare = sorted(reversed(recenti), key=lambda v: v[2] or adesso)   # dalla più vecchia

    inviate = 0
    for n, (link, titolo, data, categoria) in enumerate(da_inviare):
        if n > 0:
            time.sleep(PAUSA_TRA_MESSAGGI)
        if invia(formatta_messaggio(titolo, data, link, categoria)):
            nuovi_visti.add(link)
            inviate += 1
        else:
            print(f"⚠️ Invio fallito per {link}: riproverò alla prossima esecuzione.")
            break

    stato[NOME_FONTE] = {"visti": sorted(nuovi_visti)}
    print(f"[{NOME_FONTE}] letti {len(voci)}, inviati {inviate}")
    salva_stato(stato)


if __name__ == "__main__":
    main()
