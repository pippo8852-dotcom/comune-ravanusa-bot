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
