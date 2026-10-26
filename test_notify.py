"""Test per notify.py (bot Novità Comune di Ravanusa, stile UST Milano).
Non fanno nessuna richiesta reale a internet o a Telegram: simulano (mock) le risposte
per verificare che la logica dello script sia corretta."""
import json
import os
import re
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

import notify as nt

MESI_ABBR = {v: k.upper() for k, v in nt.MESI.items()}
SITO = "https://www.comune.ravanusa.ag.it"


def scheda(slug, titolo, data="08 OTT 26", categoria="Avvisi", assoluto=True):
    """Una scheda della pagina Novità, con la struttura vista sul sito:
    categoria e data in alto, poi il titolo come link dentro un h3."""
    href = f"{SITO}/novita/{slug}/" if assoluto else f"/novita/{slug}/"
    intestazione = ""
    if categoria:
        intestazione += (f'<a class="category" href="{SITO}/categoria-notizia/{categoria.lower()}/">'
                         f'{categoria.upper()}</a>')
    if data:
        intestazione += f'<span class="data">{data}</span>'
    return f'''
    <div class="card card-article">
      <div class="card-body">
        <div class="category-top">{intestazione}</div>
        <h3 class="card-title h5"><a class="text-decoration-none" href="{href}">
            {titolo}
        </a></h3>
        <p class="card-text">Descrizione della notizia del 1° al 31 ottobre 2026.</p>
      </div>
    </div>'''


def pagina(*schede, prima=""):
    return ("<html><body><nav><a href='/novita/'>Novità</a><a href='/servizi/'>Servizi</a></nav>"
            + prima + "".join(schede) + "<footer>Comune di Ravanusa</footer></body></html>")


def formato_sito(giorni_fa):
    """Data come la scrive il sito (es. '08 OTT 26') per una notizia di N giorni fa."""
    d = nt.oggi() - timedelta(days=giorni_fa)
    return f"{d.day:02d} {MESI_ABBR[d.month]} {str(d.year)[2:]}"


def risposta(testo, status=200):
    r = MagicMock(status_code=status, text=testo)
    if status >= 400:
        r.raise_for_status.side_effect = Exception(f"HTTP {status}")
    else:
        r.raise_for_status = lambda: None
    return r


class TestEstrazione(unittest.TestCase):
    def test_estrae_una_notizia(self):
        voci = nt.estrai_voci(pagina(scheda("refezione", "Iscrizione refezione")))
        self.assertEqual(len(voci), 1)
        link, titolo, data, categoria = voci[0]
        self.assertEqual(link, f"{SITO}/novita/refezione/")
        self.assertEqual(titolo, "Iscrizione refezione")
        self.assertEqual(data, date(2026, 10, 8))
        self.assertEqual(categoria, "AVVISI")

    def test_piu_notizie_nell_ordine_della_pagina(self):
        voci = nt.estrai_voci(pagina(scheda("a", "Prima", "26 OTT 2026"),
                                     scheda("b", "Seconda", "08 OTT 26"),
                                     scheda("c", "Terza", "06 OTT 26")))
        self.assertEqual([v[1] for v in voci], ["Prima", "Seconda", "Terza"])
        self.assertEqual([v[2] for v in voci],
                         [date(2026, 10, 26), date(2026, 10, 8), date(2026, 10, 6)])

    def test_anno_a_due_e_a_quattro_cifre(self):
        voci = nt.estrai_voci(pagina(scheda("a", "A", "26 OTT 2026"), scheda("b", "B", "26 OTT 26")))
        self.assertEqual(voci[0][2], voci[1][2])

    def test_tutti_i_mesi_abbreviati(self):
        for abbr, numero in nt.MESI.items():
            voci = nt.estrai_voci(pagina(scheda("x", "Titolo", f"05 {abbr.upper()} 26")))
            self.assertEqual(voci[0][2], date(2026, numero, 5), abbr)

    def test_data_con_spazio_non_separabile(self):
        voci = nt.estrai_voci(pagina(scheda("x", "T", "08&nbsp;OTT&nbsp;26")))
        self.assertEqual(voci[0][2], date(2026, 10, 8))

    def test_notizia_senza_categoria(self):
        voci = nt.estrai_voci(pagina(scheda("x", "Titolo", categoria=None)))
        self.assertIsNone(voci[0][3])
        self.assertEqual(voci[0][2], date(2026, 10, 8))

    def test_notizia_senza_data(self):
        voci = nt.estrai_voci(pagina(scheda("x", "Titolo", data=None)))
        self.assertEqual(len(voci), 1)
        self.assertIsNone(voci[0][2])

    def test_data_e_categoria_sono_quelle_della_propria_scheda(self):
        # la seconda scheda non ha data né categoria: non deve "rubare" quelle della prima
        voci = nt.estrai_voci(pagina(scheda("a", "Con dati", "08 OTT 26", "Avvisi"),
                                     scheda("b", "Senza dati", None, None)))
        self.assertEqual(voci[0][2], date(2026, 10, 8))
        self.assertIsNone(voci[1][2])
        self.assertIsNone(voci[1][3])

    def test_mese_sconosciuto_non_da_una_data(self):
        voci = nt.estrai_voci(pagina(scheda("x", "Titolo", "08 XYZ 26")))
        self.assertIsNone(voci[0][2])

    def test_data_impossibile_non_da_una_data(self):
        voci = nt.estrai_voci(pagina(scheda("x", "Titolo", "31 FEB 26")))
        self.assertIsNone(voci[0][2])

    def test_titolo_con_spazi_a_capo_e_codici_html(self):
        voci = nt.estrai_voci(pagina(scheda("x", "  AVVISO\n   PUBBLICO &amp; L&#8217;albo  ")))
        self.assertEqual(voci[0][1], "AVVISO PUBBLICO & L’albo")

    def test_titolo_con_tag_interni(self):
        voci = nt.estrai_voci(pagina(scheda("x", "Titolo <span>con</span> <b>tag</b>")))
        self.assertEqual(voci[0][1], "Titolo con tag")

    def test_link_relativo_diventa_assoluto(self):
        voci = nt.estrai_voci(pagina(scheda("x", "Titolo", assoluto=False)))
        self.assertEqual(voci[0][0], f"{SITO}/novita/x/")

    def test_notizie_in_evidenza_ripetute_non_duplicano(self):
        voci = nt.estrai_voci(pagina(scheda("a", "Prima", "08 OTT 26"),
                                     scheda("b", "Altra", "06 OTT 26"),
                                     scheda("a", "Prima", "26 FEB 26")))
        self.assertEqual([v[0].rsplit("/", 2)[1] for v in voci], ["a", "b"])
        self.assertEqual(voci[0][2], date(2026, 10, 8))     # vale la prima occorrenza

    def test_link_di_menu_e_altre_sezioni_sono_ignorati(self):
        altro = (f'<h3><a href="{SITO}/servizio/trasporto/">Servizio</a></h3>'
                 f'<h3><a href="{SITO}/novita/">Tutte le novità</a></h3>'
                 f'<p><a href="{SITO}/novita/solo-link-nel-testo/">non è un titolo</a></p>')
        voci = nt.estrai_voci(pagina(scheda("a", "Vera notizia"), prima=altro))
        self.assertEqual([v[1] for v in voci], ["Vera notizia"])

    def test_pagina_senza_notizie(self):
        self.assertEqual(nt.estrai_voci("<html><body>vuota</body></html>"), [])
        self.assertEqual(nt.estrai_voci(""), [])

    def test_titolo_vuoto_e_ignorato(self):
        self.assertEqual(nt.estrai_voci(pagina(scheda("x", "   "))), [])

    def test_data_nella_descrizione_non_viene_scambiata_per_quella_della_notizia(self):
        # la descrizione della prima scheda contiene "31 ottobre 2026": la seconda scheda,
        # senza data, non deve prenderla
        voci = nt.estrai_voci(pagina(scheda("a", "Prima", "08 OTT 26"),
                                     scheda("b", "Seconda", None, None)))
        self.assertIsNone(voci[1][2])


    def test_varianti_di_scrittura_della_data(self):
        varianti = [
            '<div><a href="/categoria-notizia/avvisi/">AVVISI</a> 08 OTT 26</div>',
            '<div><span>AVVISI</span> — <span>08 OTT 26</span></div>',
            '<div><span>AVVISI — 08 OTT 26</span></div>',
            '<div><time datetime="2026-10-08">08 OTT 26</time></div>',
            '<div>AVVISI 08 OTT 26</div>',
        ]
        for variante in varianti:
            html_pagina = (f'<html><body>{variante}<h3><a href="{SITO}/novita/x/">Titolo</a></h3>'
                           '</body></html>')
            voci = nt.estrai_voci(html_pagina)
            self.assertEqual(voci[0][2], date(2026, 10, 8), variante)

    def test_titolo_senza_heading_non_e_una_notizia(self):
        html_pagina = f'<html><body><div class="titolo"><a href="{SITO}/novita/x/">Titolo</a></div></body></html>'
        self.assertEqual(nt.estrai_voci(html_pagina), [])

    def test_testo_lungo_con_data_non_conta_come_data_della_scheda(self):
        html_pagina = (f'<html><body><p>Scadenza della presentazione delle domande entro il 31 ottobre 2026 '
                       f'presso gli uffici</p><h3><a href="{SITO}/novita/x/">Titolo</a></h3></body></html>')
        self.assertIsNone(nt.estrai_voci(html_pagina)[0][2])


class TestLettura(unittest.TestCase):
    def test_lettura_diretta_senza_scraperapi(self):
        with patch.object(nt, "SCRAPERAPI_KEY", None), \
             patch("notify.requests.get", return_value=risposta(pagina(scheda("a", "A")))) as get:
            voci = nt.leggi()
        self.assertEqual(len(voci), 1)
        self.assertEqual(get.call_args.args[0], f"{SITO}/novita/")
        self.assertIn("User-Agent", get.call_args.kwargs["headers"])

    def test_lettura_con_scraperapi_se_la_chiave_c_e(self):
        with patch.object(nt, "SCRAPERAPI_KEY", "chiave"), \
             patch("notify.requests.get", return_value=risposta(pagina(scheda("a", "A")))) as get:
            nt.leggi()
        self.assertEqual(get.call_args.args[0], nt.SCRAPERAPI_ENDPOINT)
        self.assertEqual(get.call_args.kwargs["params"]["url"], nt.URL)
        self.assertEqual(get.call_args.kwargs["params"]["api_key"], "chiave")

    def test_errore_http_si_propaga(self):
        with patch.object(nt, "SCRAPERAPI_KEY", None), \
             patch("notify.requests.get", return_value=risposta("", status=503)):
            with self.assertRaises(Exception):
                nt.leggi()

    def test_pagina_senza_notizie_stampa_un_brano_per_la_diagnosi(self):
        with patch.object(nt, "SCRAPERAPI_KEY", None), \
             patch("notify.requests.get", return_value=risposta("<html>layout nuovo</html>")), \
             patch("builtins.print") as stampa:
            voci = nt.leggi()
        self.assertEqual(voci, [])
        self.assertTrue(any("Nessuna notizia riconosciuta" in str(c.args[0]) for c in stampa.call_args_list))


def articolo(titolo, data="08 Ottobre 2026"):
    """Pagina di una singola notizia, con la struttura vista sul sito."""
    return (f'<html><body><h1 data-audio>{titolo}</h1><div class="row"><div class="col-6">'
            f'<small>Data:</small>\n<p class="fw-semibold font-monospace">\n   {data}   \n</p></div></div>'
            f'</body></html>')


def sitemap(*slug):
    locs = "".join(f"<url><loc>{SITO}/novita/{s}/</loc></url>" for s in slug)
    return f'<?xml version="1.0"?><urlset>{locs}</urlset>'


class TestSitemap(unittest.TestCase):
    def setUp(self):
        s = patch("notify.time.sleep")
        s.start()
        self.addCleanup(s.stop)
        p = patch.object(nt, "SCRAPERAPI_KEY", None)
        p.start()
        self.addCleanup(p.stop)

    def test_articolo_titolo_e_data(self):
        with patch("notify.requests.get", return_value=risposta(articolo("Refezione &amp; mensa"))):
            v = nt.leggi_articolo(f"{SITO}/novita/x/")
        self.assertEqual(v, (f"{SITO}/novita/x/", "Refezione & mensa", date(2026, 10, 8), None))

    def test_articolo_senza_data_o_senza_titolo(self):
        with patch("notify.requests.get", return_value=risposta("<html><h1>Solo titolo</h1></html>")):
            self.assertIsNone(nt.leggi_articolo(f"{SITO}/novita/x/")[2])
        with patch("notify.requests.get", return_value=risposta("<html>niente</html>")):
            self.assertIsNone(nt.leggi_articolo(f"{SITO}/novita/x/"))

    def test_articolo_errore_http(self):
        with patch("notify.requests.get", return_value=risposta("", status=500)):
            self.assertIsNone(nt.leggi_articolo(f"{SITO}/novita/x/"))

    def test_sitemap_legge_solo_le_ultime_e_solo_le_non_viste(self):
        pagine = {nt.SITEMAP_URL: sitemap(*[f"n{i}" for i in range(100)])}
        letti = []

        def finto_get(url, **kw):
            letti.append(url)
            return risposta(pagine.get(url) or articolo("T"))

        visti = {f"{SITO}/novita/n99/"}
        with patch("notify.requests.get", side_effect=finto_get):
            voci = nt.leggi_sitemap(visti)
        self.assertEqual(len(voci), nt.ULTIME_DA_SITEMAP - 1)
        self.assertNotIn(f"{SITO}/novita/n99/", letti)
        self.assertNotIn(f"{SITO}/novita/n0/", letti)
        self.assertIn(f"{SITO}/novita/n98/", letti)

    def test_sitemap_non_disponibile(self):
        with patch("notify.requests.get", return_value=risposta("", status=404)):
            self.assertEqual(nt.leggi_sitemap(), [])

    def test_leggi_ripiega_sulla_sitemap_se_la_pagina_non_funziona(self):
        def finto_get(url, **kw):
            if url == nt.URL:
                return risposta("<html>layout nuovo</html>")
            if url == nt.SITEMAP_URL:
                return risposta(sitemap("a", "b"))
            return risposta(articolo("Notizia"))
        with patch("notify.requests.get", side_effect=finto_get):
            voci = nt.leggi()
        self.assertEqual([v[0] for v in voci], [f"{SITO}/novita/a/", f"{SITO}/novita/b/"])

    def test_leggi_ripiega_sulla_sitemap_se_la_pagina_da_errore(self):
        def finto_get(url, **kw):
            if url == nt.URL:
                return risposta("", status=403)
            if url == nt.SITEMAP_URL:
                return risposta(sitemap("a"))
            return risposta(articolo("Notizia"))
        with patch("notify.requests.get", side_effect=finto_get):
            self.assertEqual(len(nt.leggi()), 1)

    def test_se_tutto_fallisce_l_errore_originale_si_propaga(self):
        with patch("notify.requests.get", return_value=risposta("", status=503)):
            with self.assertRaises(Exception):
                nt.leggi()

    def test_sitemap_con_scraperapi(self):
        with patch.object(nt, "SCRAPERAPI_KEY", "k"), \
             patch("notify.requests.get", return_value=risposta(sitemap())) as get:
            nt.leggi_sitemap()
        self.assertEqual(get.call_args.kwargs["params"]["url"], nt.SITEMAP_URL)


class TestFormatoMessaggio(unittest.TestCase):
    def test_struttura_del_messaggio(self):
        testo = nt.formatta_messaggio("Titolo di prova", date(2026, 10, 8),
                                      f"{SITO}/novita/x/", "AVVISI")
        righe = testo.split("\n")
        self.assertEqual(righe[0], f"{nt.NOME_FONTE} - AVVISI")
        self.assertEqual(righe[1], "Titolo di prova")
        self.assertEqual(righe[2], "📅 08/10/2026")
        self.assertEqual(righe[3], f'<a href="{SITO}/novita/x/">🔗 Leggi la notizia</a>')
        self.assertEqual(len(righe), 4)

    def test_senza_categoria_e_senza_data(self):
        testo = nt.formatta_messaggio("Titolo", None, f"{SITO}/novita/x/")
        self.assertEqual(testo.split("\n")[0], nt.NOME_FONTE)
        self.assertNotIn("📅", testo)
        self.assertEqual(len(testo.split("\n")), 3)

    def test_il_link_e_nella_scritta_e_non_scritto_per_esteso(self):
        testo = nt.formatta_messaggio("Titolo", date(2026, 10, 8), f"{SITO}/novita/x/")
        self.assertEqual(re.findall(r">([^<]*)</a>", testo), ["🔗 Leggi la notizia"])
        self.assertEqual(testo.count(f"{SITO}/novita/x/"), 1)
        self.assertNotIn("\nhttps://", testo)

    def test_caratteri_speciali_sono_escapati(self):
        testo = nt.formatta_messaggio("Orari <classi> A&B", date(2026, 10, 8),
                                      f'{SITO}/novita/x/?a=1&b="2"', "Avvisi & co")
        self.assertIn("Orari &lt;classi&gt; A&amp;B", testo)
        self.assertIn("Avvisi &amp; co", testo)
        self.assertIn('href="https://www.comune.ravanusa.ag.it/novita/x/?a=1&amp;b=&quot;2&quot;"', testo)

    def test_nessun_orario_nel_messaggio(self):
        # il sito pubblica solo la data: il messaggio non deve inventare un'ora
        testo = nt.formatta_messaggio("Titolo", date(2026, 10, 8), f"{SITO}/novita/x/")
        self.assertNotRegex(testo, r"\d{1,2}:\d{2}")


class TestInvio(unittest.TestCase):
    def setUp(self):
        for nome, valore in (("TOKEN", "tok"), ("CHAT_ID", "123")):
            p = patch.object(nt, nome, valore)
            p.start()
            self.addCleanup(p.stop)
        s = patch("notify.time.sleep")
        self.sleep = s.start()
        self.addCleanup(s.stop)

    @staticmethod
    def ok():
        r = MagicMock(status_code=200)
        r.raise_for_status = lambda: None
        return r

    @staticmethod
    def troppe(retry_after=2):
        r = MagicMock(status_code=429)
        r.json.return_value = {"parameters": {"retry_after": retry_after}}
        r.raise_for_status.side_effect = Exception("429 Too Many Requests")
        return r

    def test_parametri_della_richiesta(self):
        with patch("notify.requests.post", return_value=self.ok()) as post:
            self.assertTrue(nt.invia("messaggio"))
        dati = post.call_args.kwargs["data"]
        self.assertIn("bottok/sendMessage", post.call_args.args[0])
        self.assertEqual(dati["chat_id"], "123")
        self.assertEqual(dati["text"], "messaggio")
        self.assertEqual(dati["parse_mode"], "HTML")
        self.assertEqual(dati["disable_web_page_preview"], "true")

    def test_senza_token_non_invia(self):
        with patch.object(nt, "TOKEN", None), patch("notify.requests.post") as post:
            self.assertFalse(nt.invia("messaggio"))
        post.assert_not_called()

    def test_riprova_dopo_429_e_poi_riesce(self):
        with patch("notify.requests.post", side_effect=[self.troppe(2), self.ok()]) as post:
            self.assertTrue(nt.invia("messaggio"))
        self.assertEqual(post.call_count, 2)
        self.sleep.assert_called_once_with(3)

    def test_429_con_attesa_troppo_lunga_rinuncia(self):
        with patch("notify.requests.post", return_value=self.troppe(300)) as post:
            self.assertFalse(nt.invia("messaggio"))
        self.assertEqual(post.call_count, 1)
        self.sleep.assert_not_called()

    def test_429_continui_si_fermano_dopo_i_tentativi(self):
        with patch("notify.requests.post", return_value=self.troppe(1)) as post:
            self.assertFalse(nt.invia("messaggio"))
        self.assertEqual(post.call_count, nt.TENTATIVI_INVIO)

    def test_errore_di_rete_restituisce_false(self):
        with patch("notify.requests.post", side_effect=Exception("rete assente")):
            self.assertFalse(nt.invia("messaggio"))


class TestMain(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmp, True)
        self.percorso = Path(self._tmp) / "sent_items.json"
        for p in (patch.object(nt, "STATO", self.percorso),
                  patch.object(nt, "SCRAPERAPI_KEY", None),
                  patch.object(nt, "INVIA_AL_PRIMO_GIRO", True)):
            p.start()
            self.addCleanup(p.stop)
        s = patch("notify.time.sleep")
        self.sleep = s.start()
        self.addCleanup(s.stop)

    def esegui(self, html_pagina, esiti_invio=None):
        """Esegue main() con la pagina data. esiti_invio: lista di True/False per ogni invio."""
        with patch("notify.requests.get", return_value=risposta(html_pagina)), \
             patch("notify.invia", side_effect=esiti_invio if esiti_invio is not None
                   else (lambda testo: True)) as invia:
            nt.main()
        return invia

    def stato(self):
        return json.loads(self.percorso.read_text())

    def visti(self):
        return self.stato()[nt.NOME_FONTE]["visti"]

    def test_primo_giro_invia_le_notizie_recenti_dalla_piu_vecchia(self):
        pag = pagina(scheda("c", "Terza", formato_sito(1)), scheda("b", "Seconda", formato_sito(5)),
                     scheda("a", "Prima", formato_sito(10)))
        invia = self.esegui(pag)
        testi = [c.args[0] for c in invia.call_args_list]
        self.assertEqual(len(testi), 3)
        self.assertIn("Prima", testi[0])
        self.assertIn("Terza", testi[2])
        self.assertEqual(len(self.visti()), 3)

    def test_primo_giro_ignora_le_notizie_oltre_il_limite(self):
        pag = pagina(scheda("n", "Recente", formato_sito(2)),
                     scheda("v", "Vecchissima", formato_sito(nt.GIORNI_MASSIMI + 20)))
        invia = self.esegui(pag)
        self.assertEqual(invia.call_count, 1)
        self.assertIn("Recente", invia.call_args.args[0])
        # la vecchia viene segnata come vista: non verrà mai più valutata
        self.assertIn(f"{SITO}/novita/v/", self.visti())

    def test_primo_giro_silenzioso_se_configurato(self):
        pag = pagina(scheda("a", "Recente", formato_sito(1)))
        with patch.object(nt, "INVIA_AL_PRIMO_GIRO", False):
            invia = self.esegui(pag)
        invia.assert_not_called()
        self.assertIn(f"{SITO}/novita/a/", self.visti())

    def test_secondo_giro_non_reinvia(self):
        pag = pagina(scheda("a", "Recente", formato_sito(1)))
        self.esegui(pag)
        invia = self.esegui(pag)
        invia.assert_not_called()

    def test_notizia_nuova_dopo_il_primo_giro_viene_inviata(self):
        self.esegui(pagina(scheda("a", "Vecchia", formato_sito(3))))
        invia = self.esegui(pagina(scheda("b", "Nuova", formato_sito(0)),
                                   scheda("a", "Vecchia", formato_sito(3))))
        invia.assert_called_once()
        testo = invia.call_args.args[0]
        self.assertIn("Nuova", testo)
        self.assertIn(f'<a href="{SITO}/novita/b/">', testo)
        self.assertLess(testo.index("Nuova"), testo.index(f"{SITO}/novita/b/"))

    def test_notizia_senza_data_viene_inviata(self):
        invia = self.esegui(pagina(scheda("x", "Senza data", data=None)))
        invia.assert_called_once()
        self.assertNotIn("📅", invia.call_args.args[0])

    def test_invio_fallito_non_segna_la_notizia_e_si_ferma(self):
        pag = pagina(scheda("c", "Terza", formato_sito(1)), scheda("b", "Seconda", formato_sito(2)),
                     scheda("a", "Prima", formato_sito(3)))
        invia = self.esegui(pag, esiti_invio=[True, False])
        self.assertEqual(invia.call_count, 2)
        self.assertEqual(self.visti(), [f"{SITO}/novita/a/"])     # solo la prima è partita

    def test_notizia_fallita_viene_ritentata_alla_corsa_dopo(self):
        pag = pagina(scheda("a", "Unica", formato_sito(1)))
        self.esegui(pag, esiti_invio=[False])
        invia = self.esegui(pag)
        invia.assert_called_once()
        self.assertEqual(self.visti(), [f"{SITO}/novita/a/"])

    def test_pause_tra_i_messaggi_ma_non_prima_del_primo(self):
        pag = pagina(scheda("c", "C", formato_sito(1)), scheda("b", "B", formato_sito(2)),
                     scheda("a", "A", formato_sito(3)))
        self.esegui(pag)
        self.assertEqual(self.sleep.call_count, 2)
        self.sleep.assert_called_with(nt.PAUSA_TRA_MESSAGGI)

    def test_le_altre_chiavi_dello_stato_vengono_conservate(self):
        self.percorso.write_text(json.dumps({"feed_ravanusa": ["https://x/?p=1", "https://x/?p=2"]}))
        self.esegui(pagina(scheda("a", "Nuova", formato_sito(1))))
        stato = self.stato()
        self.assertEqual(stato["feed_ravanusa"], ["https://x/?p=1", "https://x/?p=2"])
        self.assertEqual(stato[nt.NOME_FONTE]["visti"], [f"{SITO}/novita/a/"])

    def test_errore_di_lettura_non_blocca_il_salvataggio_dello_stato(self):
        self.percorso.write_text(json.dumps({"altro": [1]}))
        with patch("notify.requests.get", side_effect=Exception("errore di rete simulato")), \
             patch("notify.invia") as invia:
            nt.main()          # non deve sollevare eccezioni
        invia.assert_not_called()
        self.assertEqual(self.stato(), {"altro": [1]})

    def test_pagina_senza_notizie_non_cambia_lo_stato(self):
        self.esegui(pagina(scheda("a", "Recente", formato_sito(1))))
        prima = self.stato()
        invia = self.esegui("<html>layout cambiato</html>")
        invia.assert_not_called()
        self.assertEqual(self.stato(), prima)

    def test_stato_corrotto_viene_trattato_come_primo_avvio(self):
        self.percorso.write_text("non è json")
        invia = self.esegui(pagina(scheda("a", "Recente", formato_sito(1))))
        invia.assert_called_once()

    def test_pagina_che_non_riconosce_nulla_all_avvio_non_crea_la_chiave(self):
        self.esegui("<html>niente</html>")
        self.assertNotIn(nt.NOME_FONTE, self.stato())


if __name__ == "__main__":
    unittest.main()
