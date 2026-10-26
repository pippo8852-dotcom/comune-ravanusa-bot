"""Test per notify.py (bot Novità Comune di Ravanusa).
Non fanno nessuna richiesta reale a internet o a Telegram: usano dati finti o il vero
feed scaricato in precedenza (feed_reale_di_prova.xml), salvato come fotografia di
riferimento."""
import json
import os
import unittest
from unittest import mock

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

import notify


def make_response(status, content, is_json=False):
    resp = mock.MagicMock()
    resp.status_code = status
    if is_json:
        resp.json.return_value = content
    else:
        resp.content = content.encode("utf-8") if isinstance(content, str) else content
        resp.text = content if isinstance(content, str) else content.decode("utf-8")
    if status >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status}")
    else:
        resp.raise_for_status = lambda: None
    return resp


RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Comune di Ravanusa</title>
<item>
    <title>Avviso pubblico &#8217; prova</title>
    <link>https://www.comune.ravanusa.ag.it/novita/avviso-prova/</link>
    <pubDate>Tue, 11 Nov 2025 15:19:20 +0000</pubDate>
    <category><![CDATA[Avvisi]]></category>
    <guid isPermaLink="false">https://www.comune.ravanusa.ag.it/?p=5510</guid>
</item>
<item>
    <title>Seconda notizia di prova</title>
    <link>https://www.comune.ravanusa.ag.it/novita/seconda-notizia/</link>
    <pubDate>Mon, 10 Nov 2025 09:00:00 +0000</pubDate>
    <category><![CDATA[Notizie]]></category>
    <guid isPermaLink="false">https://www.comune.ravanusa.ag.it/?p=5500</guid>
</item>
</channel>
</rss>"""


class FetchNovitaTests(unittest.TestCase):
    def fetch(self, content, status=200):
        with mock.patch("notify.requests.get", return_value=make_response(status, content)):
            return notify.fetch_novita()

    def test_legge_due_notizie_dal_feed(self):
        items = self.fetch(RSS_SAMPLE)
        self.assertEqual(len(items), 2)

    def test_titolo_pulito_e_senza_codici_html(self):
        items = self.fetch(RSS_SAMPLE)
        # &#8217; deve diventare un apostrofo vero, non restare come codice
        self.assertIn("’", items[0]["title"])
        self.assertNotIn("&#8217;", items[0]["title"])

    def test_link_e_id_corretti(self):
        items = self.fetch(RSS_SAMPLE)
        self.assertEqual(items[0]["link"],
                         "https://www.comune.ravanusa.ag.it/novita/avviso-prova/")
        self.assertEqual(items[0]["id"],
                         "https://www.comune.ravanusa.ag.it/?p=5510")

    def test_categoria_estratta_come_subject(self):
        items = self.fetch(RSS_SAMPLE)
        self.assertEqual(items[0]["subject"], "Avvisi")
        self.assertEqual(items[1]["subject"], "Notizie")

    def test_data_convertita_in_formato_italiano(self):
        items = self.fetch(RSS_SAMPLE)
        # 15:19 UTC del 11 novembre diventa 16:19 ora italiana (CET, UTC+1 a novembre)
        self.assertIn("11/11/2025", items[0]["date"])

    def test_feed_vuoto_restituisce_lista_vuota(self):
        vuoto = """<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>"""
        self.assertEqual(self.fetch(vuoto), [])

    def test_errore_http_passa_al_tentativo_successivo(self):
        # Il primo indirizzo (feed/) fallisce per 2 volte (FEED_ATTEMPTS=2):
        # deve passare all'API WordPress, che invece risponde subito bene.
        wp_posts = [{"id": 1, "link": "https://www.comune.ravanusa.ag.it/novita/x/",
                     "title": {"rendered": "Notizia dall'API"}, "date_gmt": "2026-01-01T10:00:00"}]
        risposte = [make_response(403, ""), make_response(403, ""),
                    make_response(200, wp_posts, is_json=True)]
        with mock.patch("notify.requests.get", side_effect=risposte), \
             mock.patch("notify.time.sleep"):
            items = notify.fetch_novita()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Notizia dall'API")


class FetchNovitaConFeedReale(unittest.TestCase):
    """Verifica il parser contro una copia reale del feed, scaricata il 25/10/2026."""

    @classmethod
    def setUpClass(cls):
        percorso = os.path.join(os.path.dirname(__file__), "feed_reale_di_prova.xml")
        with open(percorso, "r", encoding="utf-8") as f:
            cls.contenuto_feed = f.read()

    def test_legge_tutte_le_notizie_del_feed_reale(self):
        with mock.patch("notify.requests.get",
                        return_value=make_response(200, self.contenuto_feed)):
            items = notify.fetch_novita()
        # il feed scaricato conteneva 10 <item>
        self.assertEqual(len(items), 10)

    def test_ogni_notizia_ha_titolo_link_e_id(self):
        with mock.patch("notify.requests.get",
                        return_value=make_response(200, self.contenuto_feed)):
            items = notify.fetch_novita()
        for item in items:
            self.assertTrue(item["title"])
            self.assertTrue(item["link"].startswith("https://www.comune.ravanusa.ag.it"))
            self.assertTrue(item["id"])

    def test_nessun_codice_html_residuo_nei_titoli(self):
        with mock.patch("notify.requests.get",
                        return_value=make_response(200, self.contenuto_feed)):
            items = notify.fetch_novita()
        for item in items:
            self.assertNotIn("&#8217;", item["title"])
            self.assertNotIn("&amp;", item["title"])


RSS_NOVITA = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Novità</title>
<item>
    <title>Iscrizione refezione scolastica</title>
    <link>https://www.comune.ravanusa.ag.it/novita/iscrizione-refezione/</link>
    <pubDate>Thu, 08 Oct 2026 08:00:00 +0000</pubDate>
    <category><![CDATA[Avvisi]]></category>
    <guid isPermaLink="false">https://www.comune.ravanusa.ag.it/?post_type=novita&amp;p=5701</guid>
</item>
<item>
    <title>Albo presidenti di seggio</title>
    <link>https://www.comune.ravanusa.ag.it/novita/albo-presidenti-seggio/</link>
    <pubDate>Tue, 06 Oct 2026 08:00:00 +0000</pubDate>
    <category><![CDATA[Avvisi]]></category>
    <guid isPermaLink="false">https://www.comune.ravanusa.ag.it/?post_type=novita&amp;p=5698</guid>
</item>
<item>
    <title>Pagina di servizio (non è una novità)</title>
    <link>https://www.comune.ravanusa.ag.it/servizio/trasporto-scolastico/</link>
    <pubDate>Mon, 05 Oct 2026 08:00:00 +0000</pubDate>
    <guid isPermaLink="false">https://www.comune.ravanusa.ag.it/?p=5600</guid>
</item>
</channel></rss>"""

TIPI_JSON = {
    "post": {"slug": "post", "rest_base": "posts"},
    "page": {"slug": "page", "rest_base": "pages"},
    "attachment": {"slug": "attachment", "rest_base": "media"},
    "wp_block": {"slug": "wp_block", "rest_base": "blocks"},
    "notizia": {"slug": "notizia", "rest_base": "notizie"},
    "servizio": {"slug": "servizio", "rest_base": "servizi"},
}


def voce_rest(numero, giorno, link_sezione="novita"):
    return {"id": numero, "link": f"https://www.comune.ravanusa.ag.it/{link_sezione}/voce-{numero}/",
            "title": {"rendered": f"Voce {numero}"}, "date_gmt": f"2026-10-{giorno:02d}T08:00:00"}


class FetchSezioneNovitaTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("notify.time.sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def fetch(self, risposte):
        with mock.patch("notify.requests.get", side_effect=risposte) as get:
            items = notify.fetch_novita_sezione()
        return items, get

    def test_legge_il_feed_della_sezione_novita(self):
        items, get = self.fetch([make_response(200, RSS_NOVITA)])
        self.assertEqual(get.call_args_list[0].args[0],
                         "https://www.comune.ravanusa.ag.it/novita/feed/")
        self.assertEqual([i["title"] for i in items],
                         ["Iscrizione refezione scolastica", "Albo presidenti di seggio"])

    def test_l_id_e_il_link_della_notizia(self):
        items, _ = self.fetch([make_response(200, RSS_NOVITA)])
        self.assertEqual(items[0]["id"],
                         "https://www.comune.ravanusa.ag.it/novita/iscrizione-refezione/")

    def test_le_voci_fuori_dalla_sezione_novita_sono_scartate(self):
        items, _ = self.fetch([make_response(200, RSS_NOVITA)])
        self.assertTrue(all("/novita/" in i["link"] for i in items))
        self.assertEqual(len(items), 2)

    def test_data_e_categoria_restano_disponibili(self):
        items, _ = self.fetch([make_response(200, RSS_NOVITA)])
        self.assertEqual(items[0]["date"], "08/10/2026 10:00")   # 08:00 UTC = 10:00 ora legale
        self.assertEqual(items[0]["subject"], "Avvisi")

    def test_se_il_feed_fallisce_cerca_nell_api(self):
        risposte = [make_response(404, ""), make_response(404, ""),
                    make_response(200, TIPI_JSON, is_json=True),
                    make_response(200, [voce_rest(7, 8), voce_rest(6, 2)], is_json=True),
                    make_response(200, [voce_rest(9, 3, link_sezione="servizio")], is_json=True)]
        items, get = self.fetch(risposte)
        self.assertEqual([i["id"] for i in items],
                         ["https://www.comune.ravanusa.ag.it/novita/voce-7/",
                          "https://www.comune.ravanusa.ag.it/novita/voce-6/"])

    def test_l_api_interroga_solo_i_tipi_personalizzati(self):
        risposte = [make_response(404, ""), make_response(404, ""),
                    make_response(200, TIPI_JSON, is_json=True),
                    make_response(200, [], is_json=True), make_response(200, [], is_json=True)]
        _, get = self.fetch(risposte)
        urls = [c.args[0] for c in get.call_args_list]
        self.assertTrue(any("/wp/v2/notizie?" in u for u in urls))
        self.assertTrue(any("/wp/v2/servizi?" in u for u in urls))
        for standard in ("/wp/v2/posts", "/wp/v2/pages", "/wp/v2/media", "/wp/v2/blocks"):
            self.assertFalse(any(standard in u for u in urls), standard)

    def test_api_ordina_dal_piu_recente(self):
        risposte = [make_response(404, ""), make_response(404, ""),
                    make_response(200, {"a": {"slug": "a", "rest_base": "a"},
                                        "b": {"slug": "b", "rest_base": "b"}}, is_json=True),
                    make_response(200, [voce_rest(1, 2)], is_json=True),
                    make_response(200, [voce_rest(2, 9)], is_json=True)]
        items, _ = self.fetch(risposte)
        self.assertEqual([i["title"] for i in items], ["Voce 2", "Voce 1"])

    def test_feed_senza_voci_novita_passa_all_api(self):
        senza_novita = RSS_NOVITA.replace("/novita/", "/altro/")
        risposte = [make_response(200, senza_novita),
                    make_response(200, TIPI_JSON, is_json=True),
                    make_response(200, [voce_rest(7, 8)], is_json=True),
                    make_response(200, [], is_json=True)]
        items, _ = self.fetch(risposte)
        self.assertEqual([i["title"] for i in items], ["Voce 7"])

    def test_tutto_irraggiungibile_restituisce_lista_vuota(self):
        with mock.patch("notify.requests.get", return_value=make_response(503, "")):
            self.assertEqual(notify.fetch_novita_sezione(), [])

    def test_api_con_risposta_inattesa_restituisce_lista_vuota(self):
        risposte = [make_response(404, ""), make_response(404, ""),
                    make_response(200, ["non", "un", "dizionario"], is_json=True),
                    make_response(200, ["non", "un", "dizionario"], is_json=True)]
        items, _ = self.fetch(risposte)
        self.assertEqual(items, [])


class SezioneNovitaInSourcesTests(unittest.TestCase):
    def setUp(self):
        self.src = next(s for s in notify.SOURCES if s["key"] == "novita_ravanusa")
        patcher = mock.patch("notify.time.sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def giorni_fa(n):
        from datetime import datetime, timedelta
        return (datetime.now() - timedelta(days=n)).strftime("%d/%m/%Y %H:%M")

    def item(self, n, data):
        return {"id": f"https://esempio/novita/{n}/", "title": f"Notizia {n}",
                "link": f"https://esempio/novita/{n}/", "date": data, "subject": None}

    def test_la_sezione_e_attiva_e_ha_un_limite_di_eta(self):
        self.assertTrue(self.src["enabled"])
        self.assertEqual(self.src["max_age_days"], 60)

    def test_la_fonte_precedente_resta_la_prima(self):
        self.assertEqual(notify.SOURCES[0]["key"], "feed_ravanusa")

    def test_notizie_troppo_vecchie_non_vengono_inviate_ne_salvate(self):
        state = {}
        items = [self.item(2, self.giorni_fa(1)), self.item(1, self.giorni_fa(120))]
        with mock.patch.dict(self.src, {"fetch": lambda: items}), \
             mock.patch("notify.send_telegram_message", return_value=True) as send:
            notify.process_source(state, self.src)
        self.assertEqual(send.call_count, 1)
        self.assertIn("Notizia 2", send.call_args.args[0])
        self.assertEqual(state["novita_ravanusa"], ["https://esempio/novita/2/"])

    def test_notizia_al_limite_di_eta_viene_inviata(self):
        state = {}
        with mock.patch.dict(self.src, {"fetch": lambda: [self.item(1, self.giorni_fa(59))]}), \
             mock.patch("notify.send_telegram_message", return_value=True) as send:
            notify.process_source(state, self.src)
        send.assert_called_once()

    def test_notizia_senza_data_viene_inviata(self):
        state = {}
        with mock.patch.dict(self.src, {"fetch": lambda: [self.item(1, None)]}), \
             mock.patch("notify.send_telegram_message", return_value=True) as send:
            notify.process_source(state, self.src)
        send.assert_called_once()

    def test_la_fonte_senza_limite_di_eta_invia_anche_le_vecchie(self):
        # la fonte del feed principale non ha max_age_days: comportamento invariato
        vecchia = next(s for s in notify.SOURCES if s["key"] == "feed_ravanusa")
        state = {}
        with mock.patch.dict(vecchia, {"fetch": lambda: [self.item(1, self.giorni_fa(400))]}), \
             mock.patch("notify.send_telegram_message", return_value=True) as send:
            notify.process_source(state, vecchia)
        send.assert_called_once()

    def test_messaggio_con_etichetta_notizie_e_data(self):
        state = {}
        with mock.patch.dict(self.src, {"fetch": lambda: [self.item(1, self.giorni_fa(1))]}), \
             mock.patch("notify.send_telegram_message", return_value=True) as send:
            notify.process_source(state, self.src)
        msg = send.call_args.args[0]
        self.assertIn("Novità Comune di Ravanusa", msg)
        self.assertIn("Leggi la notizia</a>", msg)
        self.assertIn("🗓", msg)


class ProcessSourceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = os.path.join(os.path.dirname(__file__), "_tmp_test_state")
        os.makedirs(self._tmp, exist_ok=True)
        self._cwd = os.getcwd()
        os.chdir(self._tmp)
        notify.STATE_FILE = "sent_items.json"

    def tearDown(self):
        os.chdir(self._cwd)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def item(self, n):
        return {"id": f"id{n}", "title": f"Notizia {n}",
                "link": f"https://esempio/{n}", "date": "01/01/2026 10:00",
                "subject": "Avvisi"}

    def test_primo_giro_invia_tutte_le_notizie_lette(self):
        state = {}
        with mock.patch.dict(notify.SOURCES[0], {"fetch": lambda: [self.item(1)]}), \
             mock.patch("notify.send_telegram_message", return_value=True) as send, \
             mock.patch("notify.time.sleep"):
            notify.process_source(state, notify.SOURCES[0])
        send.assert_called_once()
        self.assertEqual(state["feed_ravanusa"], ["id1"])

    def test_notizia_gia_vista_non_viene_reinviata(self):
        state = {"feed_ravanusa": ["id1"]}
        with mock.patch.dict(notify.SOURCES[0], {"fetch": lambda: [self.item(1)]}), \
             mock.patch("notify.send_telegram_message") as send:
            notify.process_source(state, notify.SOURCES[0])
        send.assert_not_called()

    def test_ordine_di_invio_dalla_piu_vecchia_alla_piu_recente(self):
        state = {}
        ordine_inviato = []
        with mock.patch.dict(notify.SOURCES[0], {"fetch": lambda: [self.item(2), self.item(1)]}), \
             mock.patch("notify.send_telegram_message",
                        side_effect=lambda msg: (ordine_inviato.append(msg), True)[1]), \
             mock.patch("notify.time.sleep"):
            notify.process_source(state, notify.SOURCES[0])
        self.assertIn("Notizia 1", ordine_inviato[0])
        self.assertIn("Notizia 2", ordine_inviato[1])

    def test_invio_fallito_non_salva_lo_stato_e_si_ferma(self):
        state = {}
        with mock.patch.dict(notify.SOURCES[0], {"fetch": lambda: [self.item(2), self.item(1)]}), \
             mock.patch("notify.send_telegram_message", return_value=False), \
             mock.patch("notify.time.sleep"):
            notify.process_source(state, notify.SOURCES[0])
        self.assertEqual(state["feed_ravanusa"], [])


class SendTelegramTests(unittest.TestCase):
    def test_senza_token_non_invia_nulla(self):
        with mock.patch.object(notify, "TELEGRAM_TOKEN", None):
            self.assertFalse(notify.send_telegram_message("prova"))

    def test_riprova_dopo_429_e_poi_riesce(self):
        risposta_429 = make_response(429, "")
        risposta_429.json.return_value = {"parameters": {"retry_after": 0}}
        risposta_ok = make_response(200, "")
        with mock.patch("notify.requests.post", side_effect=[risposta_429, risposta_ok]) as post, \
             mock.patch("notify.time.sleep"):
            ok = notify.send_telegram_message("prova")
        self.assertTrue(ok)
        self.assertEqual(post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
