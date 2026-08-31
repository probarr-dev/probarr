"""probarr's test suite. Standard library only, no network, no ffmpeg.

Deliberately covers the pure functions and the file formats rather than the
probing: the parts that decide what a channel IS, what gets exported, and
what is remembered are exactly the parts whose failures are silent. A
mis-ranked candidate or a dropped tvg-id does not raise -- it just quietly
produces the wrong lineup, which is the failure mode this project has
actually shipped more than once.

    python3 -m unittest discover -s tests -v
"""
import datetime
import io
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probarr import aliases as aliases_mod
from probarr import curate, epg, lineups, pages, providers, settings, wantlist as wl
from probarr.normalize import (Normalizer, group_candidates,
                               declared_quality_rank, split_group_title)
from probarr.rank import rank
from probarr.sources import m3u
from probarr.sources.base import Stream
from probarr.store import RunStore


class Temp(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="probarr-test-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)


class TestNormalize(unittest.TestCase):
    def setUp(self):
        self.n = Normalizer()

    def test_packaging_is_stripped_to_one_key(self):
        names = ["UK: Meridian Sports 1", "UKFHD | Meridian Sports 1",
                 "UKUHD: Meridian Sports 1 UHD", "HEVC FHD Meridian Sports 1",
                 "Meridian Sports 1 HD [Multi-Audio]"]
        self.assertEqual(len({self.n.key(x) for x in names}), 1)

    def test_ukraine_is_not_uk(self):
        # The regression that put a Ukrainian feed on a British channel.
        self.assertNotEqual(self.n.region_of("UKRAINE: Futbol 1"), "UK")
        self.assertIn("RAINE", self.n.key("UKRAINE: Futbol 1"))

    def test_trailing_country_tag_is_also_detected(self):
        # Region tags aren't always a leading prefix -- some providers put
        # the country at the END of the name instead ("Cartoon Network | US").
        self.assertEqual(self.n.region_of("Cartoon Network | US"), "US")
        self.assertEqual(self.n.region_of("Discovery HD - UK"), "UK")
        # Must not fire on a bare substring with no separator boundary --
        # the same class of false positive test_ukraine_is_not_uk guards
        # against on the prefix side.
        self.assertIsNone(self.n.region_of("Futbol Ukraine"))

    def test_timeshift_is_a_different_channel(self):
        # The guarantee is that a +1 never lands in the base channel's pool,
        # whichever way the provider spells it.
        self.assertTrue(self.n.is_timeshift("UK: Gold +1"))
        self.assertNotEqual(self.n.key("UK: Gold +1"), self.n.key("UK: Gold"))
        self.assertNotEqual(self.n.key("UK+1 YESTERDAY+1"),
                            self.n.key("UK: Yesterday"))

    def test_alias_connects_a_renamed_brand(self):
        n = Normalizer(aliases={"UANDDRAMA": "DRAMA"})
        self.assertEqual(n.key("U&Drama"), n.key("UK: DRAMA SD"))

    def test_declared_quality_orders_candidates(self):
        self.assertGreater(declared_quality_rank("UKUHD: Channel 4K"),
                           declared_quality_rank("UK: Channel HD"))

    def test_grouping_buckets_by_identity(self):
        streams = [Stream(id=str(i), name=n, url=f"http://x/{i}")
                   for i, n in enumerate(["UK: BBC One", "UKFHD BBC One HD",
                                          "UK: ITV1"])]
        pools = group_candidates(streams, self.n)
        self.assertEqual(sorted(len(v) for v in pools.values()), [1, 2])

    def test_stylised_unicode_tags_are_still_recognised_as_tags(self):
        """Real Discord report: a provider spells its quality/format tags
        in small-caps/superscript Unicode ("ᴿᴬᵂ" for RAW, "ᵁᴴᴰ" for UHD)
        rather than plain ASCII. Those decompose to plain letters under
        NFKD, but strip() used to fold the string to ASCII only at the
        very END, after the tag-stripping regexes had already run and
        found nothing to match -- so the disguised tag survived every
        strip and got baked into the key. "NPO 1 ᴿᴬᵂ" must still collapse
        to the same key as the tag-free wantlist entry "NPO 1".
        """
        n = Normalizer(region_tags=["NL", "OD", "PLAY+", "ZG", "BE-VIP"])
        base = n.key("NPO 1")
        for name in ["NL: NPO 1 ᴿᴬᵂ NL",
                     "BE-VIP: NPO 1 ᴿᴬᵂ ",
                     "OD: NPO 1 ᴴᴰ",
                     "PLAY+: NPO 1 ᴿᴬᵂ ",
                     "ZG: NPO 1 ᴿᴬᵂ "]:
            self.assertEqual(n.key(name), base, f"{name!r} did not match")
        # A genuinely different service tier must still NOT collapse into
        # the base channel just because this fix touched the same code path.
        self.assertNotEqual(n.key("NL: NPO 1 EXTRA ᴿᴬᵂ NL"), base)


class TestSplitGroupTitle(unittest.TestCase):
    """Country + category split for Browse Channels' two-level filter.

    Real providers spell the country/category boundary differently --
    Dispatcharr's own convention pipes them ("UK | Amazon Events"), other
    panels use a colon or bare space, and the country token itself is
    sometimes a 2-letter code (US, CA) and sometimes 3-letter (USA, CAN).
    split_group_title() must handle all of these without per-provider
    configuration, reusing the same tag/separator machinery region_of()
    and group_of() already rely on.
    """

    def test_pipe_delimited_country_prefix(self):
        self.assertEqual(split_group_title("UK | Amazon Events"),
                         ("UK", "Amazon Events"))

    def test_colon_delimited_country_prefix(self):
        self.assertEqual(split_group_title("US: Sports"),
                         ("US", "Sports"))

    def test_space_delimited_country_prefix(self):
        self.assertEqual(split_group_title("US Sports HD"),
                         ("US", "Sports HD"))

    def test_three_letter_country_code(self):
        self.assertEqual(split_group_title("USA | Sports"),
                         ("US", "Sports"))
        self.assertEqual(split_group_title("CAN Locals"),
                         ("CA", "Locals"))

    def test_full_country_name(self):
        self.assertEqual(split_group_title("Canada Amazon Prime Linear"),
                         ("CA", "Amazon Prime Linear"))

    def test_no_country_marker_falls_back_to_whole_string_as_category(self):
        self.assertEqual(split_group_title("Movies"), (None, "Movies"))
        self.assertEqual(split_group_title(""), (None, ""))
        self.assertEqual(split_group_title(None), (None, ""))

    def test_ukraine_is_not_mistaken_for_uk(self):
        # Same class of false positive region_of()/group_of() already guard
        # against -- a group-title starting with "Ukraine" must not be
        # split as country=UK, category="raine ...".
        country, category = split_group_title("Ukraine Sports")
        self.assertNotEqual(country, "UK")
        self.assertEqual(category, "Ukraine Sports")


class TestBrowseCountryCategory(Temp):
    """Browse Channels' /api/browse must expose country/category for every
    provider type, not just Dispatcharr -- Xtream and M3U sources already
    carry a `group` on each Stream, it just wasn't being split or surfaced.
    """

    def _handler(self, streams):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: sent.append(body)
        patches = [
            unittest.mock.patch.object(
                web_mod.providers_mod, "get",
                lambda root, name: {"spec": "m3u://x", "scheme": "m3u"}),
            unittest.mock.patch.object(web_mod, "load_source", lambda spec: streams),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return h, sent

    def test_xtream_style_streams_get_country_and_category(self):
        streams = [
            Stream(id="1", name="BBC One", url="http://x/1", group="UK | General"),
            Stream(id="2", name="BBC Two", url="http://x/2", group="UK | General"),
            Stream(id="3", name="ESPN", url="http://x/3", group="US: Sports"),
        ]
        h, sent = self._handler(streams)
        h._browse({"provider": "prov1"})

        d = json.loads(sent[0])
        self.assertIn("countries", d)
        self.assertIn("groups", d)
        self.assertEqual(sorted(d["countries"]), ["UK", "US"])
        self.assertEqual(sorted(d["groups"]), ["General", "Sports"])
        by_name = {c["name"]: c for c in d["channels"]}
        self.assertEqual(by_name["ESPN"]["country"], "US")
        self.assertEqual(by_name["ESPN"]["group"], "Sports")

    def test_streams_without_a_recognizable_country_still_get_a_category(self):
        streams = [Stream(id="1", name="Movie Channel", url="http://x/1",
                          group="Movies")]
        h, sent = self._handler(streams)
        h._browse({"provider": "prov1"})

        d = json.loads(sent[0])
        self.assertEqual(d["countries"], [])
        self.assertEqual(d["groups"], ["Movies"])
        self.assertEqual(d["channels"][0]["country"], "")
        self.assertEqual(d["channels"][0]["group"], "Movies")


class TestWantlist(unittest.TestCase):
    def test_parses_number_name_and_tvg_id(self):
        chans, _ = wl.parse_detailed(
            "101: BBC One | bbc.one.uk\nBBC Four\n# comment\n\n", Normalizer())
        self.assertEqual(chans[0].number, 101)
        self.assertEqual(chans[0].tvg_id, "bbc.one.uk")
        self.assertEqual(chans[1].name, "BBC Four")
        self.assertEqual(len(chans), 2)

    def test_token_sort_stage_is_off_by_default(self):
        # "strict" (the default) must never invent a match a person didn't
        # explicitly ask for -- every wantlist's behaviour before this stage
        # existed has to keep reporting genuinely word-reordered names as
        # missing, not start silently guessing.
        norm = Normalizer()
        wanted, _ = wl.parse_detailed("Meridian Sports 1", norm)
        pools = {norm.key("Sports 1 Meridian"):
                [Stream(id="1", name="Sports 1 Meridian", url="http://x/1")]}
        filtered, missing, fuzzy = wl.apply(wanted, pools)
        self.assertEqual(filtered, {})
        self.assertEqual(len(missing), 1)
        self.assertEqual(fuzzy, [])

    def test_token_sort_stage_catches_reordered_words_when_enabled(self):
        norm = Normalizer()
        wanted, _ = wl.parse_detailed("Meridian Sports 1", norm)
        pools = {norm.key("Sports 1 Meridian"):
                [Stream(id="1", name="Sports 1 Meridian", url="http://x/1")]}
        filtered, missing, fuzzy = wl.apply(wanted, pools, sensitivity="normal")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(missing, [])
        self.assertEqual(len(fuzzy), 1)

    def test_token_sort_stage_refuses_an_ambiguous_pair(self):
        # Two candidates too close in score to call must still be refused,
        # the same rule every other stage in this module already follows.
        # Reordered so neither candidate is a prefix/suffix of the other or
        # of the wanted key -- this has to reach token-sort itself, not get
        # resolved (or mis-resolved) by an earlier stage first.
        norm = Normalizer()
        wanted, _ = wl.parse_detailed("Alpha Bravo Charlie", norm)
        pools = {
            norm.key("Bravo Charlie Alphaa"):
                [Stream(id="1", name="Bravo Charlie Alphaa", url="http://x/1")],
            norm.key("Charlie Alpha Bravoo"):
                [Stream(id="2", name="Charlie Alpha Bravoo", url="http://x/2")],
        }
        filtered, missing, fuzzy = wl.apply(wanted, pools, sensitivity="relaxed")
        self.assertEqual(filtered, {})
        self.assertEqual(len(missing), 1)

    def test_render_round_trips_number_group_and_tvg_id(self):
        norm = Normalizer()
        text = "[News]\n101: BBC News | bbc.news.uk\n\n[Sport]\n401: Sky Sports F1\n"
        chans, _ = wl.parse_detailed(text, norm)
        rendered = wl.render(chans)
        chans2, warnings2 = wl.parse_detailed(rendered, norm)
        self.assertEqual(warnings2, [])
        self.assertEqual([c.as_dict() for c in chans], [c.as_dict() for c in chans2])

    def test_group_together_collapses_a_scattered_group_into_one_run(self):
        norm = Normalizer()
        # News/Sport/News: the second News channel is scattered away from
        # the first by a Sport channel in between -- group_together must
        # pull both News channels together into a single contiguous block,
        # not just leave file order alone.
        text = "[News]\nBBC News\n[Sport]\nSky Sports F1\n[News]\nSky News\n"
        chans, _ = wl.parse_detailed(text, norm)
        grouped = wl.group_together(chans)
        self.assertEqual([c.name for c in grouped],
                         ["BBC News", "Sky News", "Sky Sports F1"])
        rendered = wl.render(grouped)
        self.assertEqual(rendered.count("[News]"), 1)
        self.assertEqual(rendered.count("[Sport]"), 1)

    def test_group_together_keeps_relative_order_within_a_group(self):
        norm = Normalizer()
        text = "[News]\nBBC News\nSky News\nITV News\n"
        chans, _ = wl.parse_detailed(text, norm)
        grouped = wl.group_together(chans)
        self.assertEqual([c.name for c in grouped], ["BBC News", "Sky News", "ITV News"])

    def test_group_together_pushes_the_ungrouped_bucket_to_the_end(self):
        # A wide EPG import against a narrow reference lineup leaves most
        # channels with no group at all -- if that bucket happens to appear
        # early in the file, it must not bury groups discovered later in
        # a wall of blanks (this is exactly what real reference-lineup
        # enrichment looked like: Entertainment matched, then a huge
        # unmatched run, with News/Sports/etc still fully numbered further
        # down -- easy to mistake for enrichment having stopped working).
        norm = Normalizer()
        text = "[Entertainment]\n4seven\n[]\nUnmatched One\nUnmatched Two\n[News]\nBBC News\n"
        chans, _ = wl.parse_detailed(text, norm)
        grouped = wl.group_together(chans)
        self.assertEqual([c.group for c in grouped],
                         ["Entertainment", "News", None, None])

    def test_channels_from_reference_builds_a_full_wantlist(self):
        norm = Normalizer()
        data = {"categories": {"News": [{"name": "BBC News", "number": 503},
                                         {"name": "CNBC", "number": 505}],
                                "Sport": [{"name": "Sky Sports F1", "number": 407}]}}
        chans = wl.channels_from_reference(data, norm)
        self.assertEqual(len(chans), 3)
        by_name = {c.name: c for c in chans}
        self.assertEqual(by_name["BBC News"].number, 503)
        self.assertEqual(by_name["BBC News"].group, "News")
        self.assertEqual(by_name["Sky Sports F1"].group, "Sport")
        rendered = wl.render(wl.group_together(chans))
        self.assertIn("[News]", rendered)
        self.assertIn("503: BBC News", rendered)

    def test_channels_from_reference_drops_duplicate_names_across_categories(self):
        # A name appearing in two categories (real data does this) must not
        # produce two lines for the same channel -- first one wins, same
        # rule as reference_lineup_map.
        norm = Normalizer()
        data = {"categories": {"A": [{"name": "Foo", "number": 1}],
                                "B": [{"name": "Foo", "number": 2}]}}
        chans = wl.channels_from_reference(data, norm)
        self.assertEqual(len(chans), 1)
        self.assertEqual(chans[0].number, 1)

    def test_channels_from_reference_rejects_unrecognised_shape(self):
        with self.assertRaises(ValueError):
            wl.channels_from_reference({"channels": []}, Normalizer())

    def test_reference_lineup_map_flattens_categories(self):
        data = {"categories": {"News": [{"name": "BBC News", "number": 231}],
                                "Sport": [{"name": "Sky Sports F1", "number": 401}]}}
        norm = Normalizer()
        m = wl.reference_lineup_map(data, norm)
        self.assertEqual(m[norm.key("BBC News")], (231, "News"))
        self.assertEqual(m[norm.key("Sky Sports F1")], (401, "Sport"))

    def test_reference_lineup_map_rejects_unrecognised_shape(self):
        with self.assertRaises(ValueError):
            wl.reference_lineup_map({"channels": []}, Normalizer())

    def test_reference_label_splits_country_and_package(self):
        self.assertEqual(wl._reference_label("UK_SkyTV_lineup.json"),
                          ("United Kingdom", "SkyTV"))
        self.assertEqual(wl._reference_label("US_DISH-Top250_lineup.json"),
                          ("United States", "DISH Top250"))
        self.assertEqual(wl._reference_label("plugin.json")[0], "Other")

    def test_enrich_only_fills_gaps_never_overwrites(self):
        norm = Normalizer()
        # "BBC News" has no number/group and should be filled; "Sky Sports F1"
        # already has both and must be left exactly as the operator set them.
        chans, _ = wl.parse_detailed(
            "BBC News\n[Football]\n999: Sky Sports F1\n", norm)
        ref = wl.reference_lineup_map(
            {"categories": {"News": [{"name": "BBC News", "number": 231}],
                             "Sport": [{"name": "Sky Sports F1", "number": 401}]}}, norm)
        chans, matched = wl.enrich_with_reference(chans, ref)
        self.assertEqual(matched, 1)
        by_name = {c.name: c for c in chans}
        self.assertEqual(by_name["BBC News"].number, 231)
        self.assertEqual(by_name["BBC News"].group, "News")
        self.assertEqual(by_name["Sky Sports F1"].number, 999)
        self.assertEqual(by_name["Sky Sports F1"].group, "Football")


class TestProbeQueueGate(unittest.TestCase):
    def test_gate_is_called_with_the_next_jobs_lane(self):
        # Real bug: the viewer gate used to be asked with no arguments at
        # all, so it had no way to know which provider's connections a live
        # viewer was actually competing against -- it could only ever
        # assume a single shared connection, even for a lane saved with
        # its own higher concurrency. The queue must pass the lane of
        # whichever job would launch next.
        import time as time_mod
        from probarr.probequeue import ProbeQueue

        seen_lanes = []
        def gate(lane=None):
            seen_lanes.append(lane)
            return None   # never block, just observe what we were asked

        results = []
        def runner(payload):
            results.append(payload["lane"])
            return {"status": "ok"}

        q = ProbeQueue(runner, concurrency=lambda: 1, gap=lambda: 0,
                       gate=gate)
        q.submit("k1", {"lane": "mybunny"})
        for _ in range(50):
            if results:
                break
            time_mod.sleep(0.02)
        self.assertIn("mybunny", results)
        self.assertIn("mybunny", seen_lanes)

    def test_a_gate_bug_is_not_silently_retried_as_a_zero_arg_gate(self):
        # Real bug found on a full-codebase review: the queue used to call
        # self._gate(next_lane), and treated ANY TypeError as "this must
        # be an old-style zero-arg gate", silently retrying with no
        # arguments at all. A lane-aware gate with a genuine internal bug
        # (raises TypeError for a reason that has nothing to do with
        # arity) was misdiagnosed exactly the same way and got quietly
        # retried with the wrong arity instead of the bug being visible.
        # Fixed by deciding the calling convention ONCE from the gate's
        # real signature (inspect.signature), not from whether calling it
        # happens to raise. This asserts that decision directly: a
        # 1-parameter gate is always called WITH the lane, a 0-parameter
        # gate always WITHOUT it -- never a silent fallback between them.
        from probarr.probequeue import ProbeQueue

        def one_param_gate(lane):
            return None
        q1 = ProbeQueue(lambda p: {"status": "ok"}, gate=one_param_gate)
        self.assertTrue(q1._gate_takes_lane)

        def zero_param_gate():
            return None
        q2 = ProbeQueue(lambda p: {"status": "ok"}, gate=zero_param_gate)
        self.assertFalse(q2._gate_takes_lane)

    def test_gate_without_a_lane_parameter_still_works(self):
        # Backward compatibility: a gate written before the lane argument
        # existed (just `lambda: None`) must not break the queue.
        import time as time_mod
        from probarr.probequeue import ProbeQueue

        results = []
        q = ProbeQueue(lambda payload: results.append(payload["lane"]) or {"status": "ok"},
                       concurrency=lambda: 1, gap=lambda: 0,
                       gate=lambda: None)
        q.submit("k1", {"lane": "mybunny"})
        for _ in range(50):
            if results:
                break
            time_mod.sleep(0.02)
        self.assertIn("mybunny", results)

    def test_settle_gap_applies_only_when_the_lane_was_genuinely_full(self):
        # User-specified rule: if a lane's connections (probes + live
        # viewers) are all in use, wait LANE_SETTLE_SECONDS after one frees
        # before reusing it -- a provider seen live to serve a connection
        # accepted too soon after the previous one closed as corrupted
        # (decode errors, no frame produced) rather than cleanly refuse it.
        # But a lane with genuine spare capacity must never pay this: two
        # probes running against a 4-connection lane with one viewer still
        # leaves a free slot, and a third probe should start immediately.
        import time as time_mod
        import threading as threading_mod
        from probarr import probequeue as pq_mod
        from probarr.probequeue import ProbeQueue

        orig_settle = pq_mod.LANE_SETTLE_SECONDS
        pq_mod.LANE_SETTLE_SECONDS = 0.3
        try:
            release = threading_mod.Event()
            started = []
            finished = []
            def runner(payload):
                started.append((payload["key"], time_mod.time()))
                if payload["key"] == "hold":
                    release.wait(timeout=2)
                finished.append((payload["key"], time_mod.time()))
                return {"status": "ok"}

            # limit=2, one viewer -> only ONE probe slot genuinely free.
            q = ProbeQueue(runner, concurrency=lambda: 2, gap=lambda: 0,
                           lane_limit=lambda lane: 2, viewer_count=lambda lane: 1)
            q.submit("hold", {"lane": "L", "key": "hold"})
            for _ in range(50):
                if started:
                    break
                time_mod.sleep(0.02)
            self.assertEqual(len(started), 1)   # the lane was already full (1 probe + 1 viewer = 2)

            q.submit("next", {"lane": "L", "key": "next"})
            release.set()   # "hold" finishes now -- lane was full, settle gap must apply
            for _ in range(100):
                if len(started) >= 2:
                    break
                time_mod.sleep(0.02)
            gap = started[1][1] - finished[0][1]
            self.assertGreaterEqual(gap, pq_mod.LANE_SETTLE_SECONDS * 0.8,
                                    "next probe started before the settle gap elapsed")
        finally:
            pq_mod.LANE_SETTLE_SECONDS = orig_settle

    def test_settle_gap_does_not_apply_when_the_lane_has_spare_capacity(self):
        import time as time_mod
        from probarr import probequeue as pq_mod
        from probarr.probequeue import ProbeQueue

        orig_settle = pq_mod.LANE_SETTLE_SECONDS
        pq_mod.LANE_SETTLE_SECONDS = 5   # deliberately large -- must not be waited for
        try:
            started = []
            def runner(payload):
                started.append(payload["key"])
                return {"status": "ok"}

            # limit=4, one viewer, one probe running at most -> always spare.
            q = ProbeQueue(runner, concurrency=lambda: 4, gap=lambda: 0,
                           lane_limit=lambda lane: 4, viewer_count=lambda lane: 1)
            q.submit("a", {"lane": "L", "key": "a"})
            q.submit("b", {"lane": "L", "key": "b"})
            t0 = time_mod.time()
            for _ in range(100):
                if len(started) >= 2:
                    break
                time_mod.sleep(0.02)
            self.assertLess(time_mod.time() - t0, 2,
                            "second probe waited as if the lane were full")
            self.assertEqual(set(started), {"a", "b"})
        finally:
            pq_mod.LANE_SETTLE_SECONDS = orig_settle

    def test_same_channel_candidates_never_run_simultaneously(self):
        # Real, directly-evidenced case: two quality-variant candidates of
        # ONE channel launched in the same second (genuine lane capacity
        # to spare -- this isn't the settle-gap case) and both came back
        # corrupted, while the exact same URL decoded perfectly cleanly in
        # complete isolation moments later. The provider's per-channel
        # backend relay, not the account's overall connection count, is
        # what can't be shared -- so same-channel candidates must queue
        # behind each other even when the lane itself has room.
        import time as time_mod
        import threading as threading_mod
        from probarr.probequeue import ProbeQueue

        release = threading_mod.Event()
        running_together = []
        active = set()
        lock = threading_mod.Lock()
        def runner(payload):
            with lock:
                active.add(payload["rec_key"])
                running_together.append(set(active))
            if payload["rec_key"].startswith("BBCONE|"):
                release.wait(timeout=2)
            with lock:
                active.discard(payload["rec_key"])
            return {"status": "ok"}

        # Plenty of lane capacity (4) and no viewers -- if this were purely
        # about lane capacity, both BBCONE candidates would run at once.
        q = ProbeQueue(runner, concurrency=lambda: 4, gap=lambda: 0,
                       lane_limit=lambda lane: 4, viewer_count=lambda lane: 0)
        q.submit("k1", {"lane": "L", "rec_key": "BBCONE|streamA"})
        q.submit("k2", {"lane": "L", "rec_key": "BBCONE|streamB"})
        q.submit("k3", {"lane": "L", "rec_key": "BBCTWO|streamC"})
        for _ in range(50):
            if len(running_together) >= 2:
                break
            time_mod.sleep(0.02)
        # BBCTWO (a different channel) must be able to run alongside the
        # first BBCONE candidate -- confirms this isn't just serialising
        # everything.
        self.assertTrue(any(len(s) >= 2 for s in running_together),
                        "a different channel never ran alongside the first")
        # But no snapshot may ever show BOTH BBCONE candidates active at once.
        both_bbcone = {"BBCONE|streamA", "BBCONE|streamB"}
        self.assertFalse(any(both_bbcone.issubset(s) for s in running_together),
                         "two candidates of the same channel ran simultaneously")
        release.set()


class TestProbeQueueSnapshotNeverLeaksSeedUrls(unittest.TestCase):
    """snapshot() feeds /api/queue, a public endpoint every page's topbar
    now polls for the "diagnosing" badge. A never-before-queued candidate's
    payload carries a `seed` dict with the stream's REAL url (credentials
    and all, same as every other place in this app that redacts a URL
    before it reaches a browser) -- snapshot() must expose only the fields
    the badge actually needs (run_id/rec_key/lane/diagnose), never the raw
    payload."""

    def test_snapshot_omits_seed_and_url_entirely(self):
        import time as time_mod
        from probarr.probequeue import ProbeQueue
        release = __import__("threading").Event()

        def runner(payload):
            release.wait(2)
            return {"status": "ok"}

        q = ProbeQueue(runner, concurrency=lambda: 1, gap=lambda: 0)
        q.submit("k1", {"run_id": "run1", "rec_key": "BBCONE|s1", "lane": "mybunny",
                        "diagnose": True,
                        "seed": {"url": "http://user:pass@provider.example/live/1"}})
        snap = None
        for _ in range(50):
            snap = q.snapshot()
            if snap["keys"]:
                break
            time_mod.sleep(0.02)
        release.set()
        raw = __import__("json").dumps(snap)
        self.assertNotIn("seed", raw)
        self.assertNotIn("user:pass", raw)
        self.assertNotIn("provider.example", raw)
        entry = snap["keys"]["k1"]
        self.assertEqual(entry["run_id"], "run1")
        self.assertEqual(entry["rec_key"], "BBCONE|s1")
        self.assertEqual(entry["lane"], "mybunny")
        self.assertTrue(entry["diagnose"])


class TestVerifyStop(Temp):
    def test_should_stop_actually_cuts_a_concurrent_run_short(self):
        # Real bug: with concurrency>1, ThreadPoolExecutor.submit() only
        # queues work and returns immediately, so the submit loop raced
        # through the ENTIRE worklist (hundreds of items) before a
        # should_stop() flip from an HTTP request could ever land -- and
        # the as_completed() loop that followed had no should_stop check at
        # all, so it unconditionally waited for every queued item to
        # finish. Stop verifying was a complete no-op on any concurrency>1
        # run until it had probed everything anyway. Reproduced here with a
        # slow, mocked probe() and a should_stop that flips after the first
        # completion -- far fewer than all 40 candidates must run.
        import time as time_mod
        from probarr import verify as verify_mod
        from probarr.sources.base import Stream
        from probarr.probe import ProbeOptions
        from probarr.store import RunStore

        store = RunStore(self.root, "run1")
        store.write_wantlist_raw(
            [{"number": i, "name": f"C{i}", "key": f"C{i}"} for i in range(40)], [])
        pools = {f"C{i}": [Stream(id=f"s{i}", name=f"C{i}", url=f"http://x/{i}")]
                for i in range(40)}

        call_count = [0]
        def fake_probe(stream, opts, thumb_path, frame_path, crop_path):
            call_count[0] += 1
            time_mod.sleep(0.05)
            return {"status": "ok"}

        stop_after_first = [False]
        def should_stop():
            return stop_after_first[0]

        with unittest.mock.patch("probarr.verify.probe", fake_probe):
            def progress_cb(*a, **k):
                if call_count[0] >= 1:
                    stop_after_first[0] = True
            verify_mod.verify(pools, store, ProbeOptions(), concurrency=4,
                              gap_seconds=0, should_stop=should_stop,
                              progress_cb=progress_cb)

        # With 4 workers and a stop flipped after the very first completion,
        # nowhere near all 40 candidates should have been probed -- the old
        # code would have run every single one regardless.
        self.assertLess(call_count[0], 40)
        meta = store.read_meta()
        self.assertTrue(meta.get("interrupted"))

    def test_budget_seconds_actually_cuts_a_concurrent_run_short(self):
        # Real bug found on a full-codebase review: the concurrency>1
        # branch checked should_stop() in its as_completed loop but never
        # budget_seconds, unlike the serial branch a few lines above it --
        # a scheduled lineup with concurrency>1 and a time budget ran to
        # completion of the entire worklist regardless of elapsed time.
        # Same shape as the should_stop test above: a slow mocked probe()
        # and a budget that expires well before all 40 candidates finish.
        import time as time_mod
        from probarr import verify as verify_mod
        from probarr.sources.base import Stream
        from probarr.probe import ProbeOptions
        from probarr.store import RunStore

        store = RunStore(self.root, "run1")
        store.write_wantlist_raw(
            [{"number": i, "name": f"C{i}", "key": f"C{i}"} for i in range(40)], [])
        pools = {f"C{i}": [Stream(id=f"s{i}", name=f"C{i}", url=f"http://x/{i}")]
                for i in range(40)}

        call_count = [0]
        def fake_probe(stream, opts, thumb_path, frame_path, crop_path):
            call_count[0] += 1
            time_mod.sleep(0.1)
            return {"status": "ok"}

        with unittest.mock.patch("probarr.verify.probe", fake_probe):
            verify_mod.verify(pools, store, ProbeOptions(), concurrency=4,
                              gap_seconds=0, budget_seconds=0.15)

        # 4 workers, each probe takes 0.1s, budget is 0.15s -- the first
        # wave of up to 4 completes, then the budget check must stop
        # further work from being queued or awaited. The old code ignored
        # budget_seconds entirely here and would have run all 40.
        self.assertLess(call_count[0], 40)
        meta = store.read_meta()
        self.assertTrue(meta.get("interrupted"))


class TestRateLimitGuard(Temp):
    """New: probe.py flags HTTP 429/403 in ffmpeg stderr distinctly from a
    genuinely dead/corrupted stream, and verify.py's RateLimitGuard pauses
    ALL probing (not just the one channel) when the provider is actively
    refusing connections -- ported from PiratesIRC's IPTVChecker, which had
    this and probarr previously did not.
    """

    def test_probe_detects_429_in_stderr_and_labels_it_distinctly(self):
        from probarr import probe as probe_mod

        self.assertTrue(probe_mod._RATE_LIMIT_RE.search(
            "Server returned 429 Too Many Requests"))
        self.assertTrue(probe_mod._RATE_LIMIT_RE.search(
            "HTTP error 403 Forbidden"))
        self.assertFalse(probe_mod._RATE_LIMIT_RE.search(
            "Connection timed out"))
        self.assertFalse(probe_mod._RATE_LIMIT_RE.search(
            "concealing 12 DC coefficients"))

    def test_full_probe_marks_no_frame_as_rate_limited_when_stderr_says_429(self):
        # Real, evidenced shape from live investigation: metadata succeeds
        # (ffprobe sees a video stream) but the capture pass gets nothing --
        # here because the provider actively refused it, not because the
        # stream is dead. The reason string must say so, distinctly from
        # the generic "no frame could be decoded".
        import unittest.mock
        from probarr import probe as probe_mod
        from probarr.sources.base import Stream

        opts = probe_mod.ProbeOptions(retry_empty=False)
        stream = Stream(id="s1", name="Comedy Central", url="http://x/429")

        fake_meta = {"has_video": True, "width": 1920, "height": 1080,
                    "fps": 50.0, "video_codec": "h264", "video_profile": "",
                    "pix_fmt": "yuv420p", "audio_codec": "aac",
                    "audio_channels": 2, "video_variant_count": 1,
                    "declared_kbps": 0, "container": "mpegts"}
        fake_cap = {"decode_errors": 0, "corruption_errors": 0,
                   "corruption_startup": 0, "corruption_steady": 0,
                   "corruption_per_sec": 0.0, "decoded_seconds": 0.0,
                   "error_samples": ["Server returned 403 Forbidden"],
                   "capture_seconds": 0.1, "timed_out": False,
                   "rate_limited": True, "dhash": None, "motion": None,
                   "motion_frames": 0, "low_motion": False, "frame32": None,
                   "low_contrast": False, "measured_kbps": 0,
                   "sample_duration": 0.0, "thumb": None, "frame": None,
                   "crop": None, "clip": None}

        with unittest.mock.patch.object(probe_mod, "probe_metadata", return_value=fake_meta), \
             unittest.mock.patch.object(probe_mod, "capture", return_value=fake_cap):
            result = probe_mod.probe(stream, opts, "/tmp/t.jpg")

        self.assertEqual(result["status"], probe_mod.STATUS_NO_FRAME)
        self.assertTrue(result["rate_limited"])
        self.assertIn("429/403", result["reason"])
        self.assertNotIn("no frame could be decoded", result["reason"])

    def test_guard_trips_after_threshold_hits_and_pauses_the_caller(self):
        import time as time_mod
        from probarr.verify import RateLimitGuard

        guard = RateLimitGuard()
        guard.BASE_COOLDOWN_SECONDS = 0.3   # keep the test fast
        guard.TRIP_THRESHOLD = 3

        logged = []
        for _ in range(3):
            guard.record_hit(log=logged.append)

        self.assertEqual(guard.trips, 1)
        self.assertTrue(any("tripped" in m for m in logged))

        start = time_mod.time()
        guard.wait()
        elapsed = time_mod.time() - start
        # Must genuinely have paused for close to the cooldown, not returned
        # immediately.
        self.assertGreaterEqual(elapsed, 0.3 * 0.7)

    def test_guard_does_not_trip_below_threshold(self):
        from probarr.verify import RateLimitGuard
        guard = RateLimitGuard()
        guard.record_hit()
        guard.record_hit()
        self.assertEqual(guard.trips, 0)
        # No cooldown active -- must return immediately.
        import time as time_mod
        start = time_mod.time()
        guard.wait()
        self.assertLess(time_mod.time() - start, 0.05)

    def test_verify_run_pauses_all_probing_when_provider_starts_refusing(self):
        # End-to-end through verify(): three channels' first candidates all
        # come back 429-refused in quick succession (below the real
        # per-channel/per-lane fixes' reach, since this is a DIFFERENT
        # channel each time) -- the guard must still trip and pause the
        # 4th probe, proving the pause is account-wide, not per-channel.
        import time as time_mod
        import unittest.mock
        from probarr import verify as verify_mod
        from probarr.probe import ProbeOptions, STATUS_NO_FRAME
        from probarr.sources.base import Stream
        from probarr.store import RunStore

        store = RunStore(self.root, "run1")
        store.write_wantlist_raw(
            [{"number": i, "name": f"C{i}", "key": f"C{i}"} for i in range(4)], [])
        pools = {f"C{i}": [Stream(id=f"s{i}", name=f"C{i}", url=f"http://x/{i}")]
                for i in range(4)}

        call_times = []

        def fake_probe(stream, opts, thumb_path, frame_path=None, crop_path=None):
            call_times.append(time_mod.time())
            if len(call_times) <= 3:
                return {"status": STATUS_NO_FRAME, "rate_limited": True,
                       "reason": "provider refused the connection (429/403)"}
            return {"status": "ok", "rate_limited": False}

        with unittest.mock.patch("probarr.verify.probe", fake_probe), \
             unittest.mock.patch.object(verify_mod.RateLimitGuard,
                                        "BASE_COOLDOWN_SECONDS", 0.4), \
             unittest.mock.patch.object(verify_mod.RateLimitGuard,
                                        "TRIP_THRESHOLD", 3):
            verify_mod.verify(pools, store, ProbeOptions(), concurrency=1,
                              gap_seconds=0)

        self.assertEqual(len(call_times), 4)
        # The 4th call (past the trip threshold) must land noticeably later
        # than the first three, which fired back-to-back.
        gap_before_trip = call_times[2] - call_times[0]
        gap_after_trip = call_times[3] - call_times[2]
        self.assertGreater(gap_after_trip, gap_before_trip)
        self.assertGreaterEqual(gap_after_trip, 0.4 * 0.7)

    def test_concurrent_verify_never_runs_two_candidates_of_the_same_channel(self):
        # verify.py's concurrency>1 branch had NO per-channel single-flight
        # equivalent to probequeue.py's -- this is the gap that made the
        # earlier probequeue-only fix invisible to a real "Verify" run using
        # several provider slots. Two candidates of ONE channel plus one
        # candidate of a different channel, concurrency=3: the different
        # channel may overlap either same-channel candidate, but the two
        # same-channel candidates must never overlap each other.
        import threading
        import time as time_mod
        import unittest.mock
        from probarr import verify as verify_mod
        from probarr.probe import ProbeOptions
        from probarr.sources.base import Stream
        from probarr.store import RunStore

        store = RunStore(self.root, "run1")
        store.write_wantlist_raw(
            [{"number": 1, "name": "SAME", "key": "SAME"},
             {"number": 2, "name": "OTHER", "key": "OTHER"}], [])
        pools = {
            "SAME": [Stream(id="a", name="SAME-a", url="http://x/a"),
                    Stream(id="b", name="SAME-b", url="http://x/b")],
            "OTHER": [Stream(id="c", name="OTHER-c", url="http://x/c")],
        }

        active = set()
        overlap_detected = [False]
        lock = threading.Lock()

        def fake_probe(stream, opts, thumb_path, frame_path=None, crop_path=None):
            with lock:
                if stream.id in ("a", "b") and any(s in ("a", "b") for s in active):
                    overlap_detected[0] = True
                active.add(stream.id)
            time_mod.sleep(0.1)
            with lock:
                active.discard(stream.id)
            return {"status": "ok"}

        with unittest.mock.patch("probarr.verify.probe", fake_probe):
            verify_mod.verify(pools, store, ProbeOptions(), concurrency=3,
                              gap_seconds=0, clean_target=None)

        self.assertFalse(overlap_detected[0],
                         "two candidates of the same channel ran simultaneously")


class TestProviderDeclined(Temp):
    """The real, measured failure this was built for.

    Signature taken from an actual 733-probe run: all 44 no_frame results
    had decoded_seconds 0.00, measured_kbps 0, decode errors present, and
    timed_out False -- the provider accepted the connection and handed back
    undecodable bytes rather than refusing. They arrived in same-channel
    bursts, and every failing URL probed clean elsewhere in the same run.
    """

    def _cap(self, **over):
        cap = {"decode_errors": 96, "corruption_errors": 40,
              "corruption_startup": 40, "corruption_steady": 0,
              "corruption_per_sec": 0.0, "decoded_seconds": 0.0,
              "error_samples": ["[h264] non-existing PPS 0 referenced"],
              "capture_seconds": 5.2, "timed_out": False,
              "rate_limited": False, "dhash": None, "motion": None,
              "motion_frames": 0, "low_motion": False, "frame32": None,
              "low_contrast": False, "measured_kbps": 0,
              "sample_duration": 0.0, "thumb": None, "frame": None,
              "crop": None, "clip": None}
        cap.update(over)
        return cap

    def test_recognises_the_measured_signature(self):
        from probarr.probe import served_nothing
        self.assertTrue(served_nothing(self._cap()))

    def test_does_not_fire_on_ambiguous_lookalikes(self):
        from probarr.probe import served_nothing
        # Decoded real video but the thumbnail selection missed -- a
        # different fault, must keep the cheap single retry.
        self.assertFalse(served_nothing(self._cap(decoded_seconds=10.9,
                                                  measured_kbps=2608)))
        # Bytes arrived even though decode reported nothing.
        self.assertFalse(served_nothing(self._cap(measured_kbps=2608)))
        # A clean capture that produced a picture is never this.
        self.assertFalse(served_nothing(self._cap(thumb="/tmp/a.jpg")))
        # No errors at all -- not the garbage-stream shape.
        self.assertFalse(served_nothing(self._cap(decode_errors=0)))

    def test_backs_off_properly_instead_of_retrying_once_immediately(self):
        # The old behaviour was ONE retry after 1.5s, which every one of the
        # 44 real failures had already used and still failed, because the
        # same-channel burst causing it was still in flight. The retry must
        # now escalate and span long enough for that burst to drain.
        import unittest.mock
        from probarr import probe as probe_mod
        from probarr.sources.base import Stream

        opts = probe_mod.ProbeOptions(empty_backoff=(0.05, 0.1, 0.2))
        stream = Stream(id="s1", name="Comedy Central", url="http://x/cc")
        meta = {"has_video": True, "width": 1920, "height": 1080, "fps": 50.0,
               "video_codec": "h264", "video_profile": "", "pix_fmt": "yuv420p",
               "audio_codec": "aac", "audio_channels": 2,
               "video_variant_count": 1, "declared_kbps": 0,
               "container": "mpegts"}

        sleeps = []
        calls = [0]

        def fake_capture(*a, **k):
            calls[0] += 1
            return self._cap()

        with unittest.mock.patch.object(probe_mod, "probe_metadata", return_value=meta), \
             unittest.mock.patch.object(probe_mod, "capture", side_effect=fake_capture), \
             unittest.mock.patch.object(probe_mod.time, "sleep", sleeps.append):
            result = probe_mod.probe(stream, opts, "/tmp/t.jpg")

        self.assertEqual(calls[0], 4)                 # initial + 3 retries
        self.assertEqual(sleeps, [0.05, 0.1, 0.2])    # escalating, not 1.5 once
        self.assertEqual(result["status"], probe_mod.STATUS_NO_FRAME)
        self.assertTrue(result["provider_declined"])
        self.assertIn("declining to serve", result["reason"])

    def test_stops_retrying_as_soon_as_a_frame_arrives(self):
        # The whole premise is that these clear on their own -- so a retry
        # that succeeds must not keep burning provider connections, and the
        # result must be a normal verdict, not no_frame.
        import unittest.mock
        from probarr import probe as probe_mod
        from probarr.sources.base import Stream

        opts = probe_mod.ProbeOptions(empty_backoff=(0.05, 0.1, 0.2))
        stream = Stream(id="s1", name="Comedy Central", url="http://x/cc")
        meta = {"has_video": True, "width": 1920, "height": 1080, "fps": 50.0,
               "video_codec": "h264", "video_profile": "", "pix_fmt": "yuv420p",
               "audio_codec": "aac", "audio_channels": 2,
               "video_variant_count": 1, "declared_kbps": 0,
               "container": "mpegts"}
        calls = [0]

        def fake_capture(*a, **k):
            calls[0] += 1
            if calls[0] < 3:
                return self._cap()
            return self._cap(thumb="/tmp/t.jpg", decoded_seconds=10.9,
                            measured_kbps=2608, decode_errors=12,
                            corruption_startup=12)

        with unittest.mock.patch.object(probe_mod, "probe_metadata", return_value=meta), \
             unittest.mock.patch.object(probe_mod, "capture", side_effect=fake_capture), \
             unittest.mock.patch.object(probe_mod.time, "sleep", lambda s: None):
            result = probe_mod.probe(stream, opts, "/tmp/t.jpg")

        self.assertEqual(calls[0], 3)                 # stopped on success
        self.assertEqual(result["status"], probe_mod.STATUS_OK)
        self.assertEqual(result["attempts"], 3)

    def test_an_ordinary_empty_capture_keeps_the_cheap_single_retry(self):
        # Not every empty capture is a provider refusal -- one that decoded
        # real video but produced no picture must not pay the long backoff.
        import unittest.mock
        from probarr import probe as probe_mod
        from probarr.sources.base import Stream

        opts = probe_mod.ProbeOptions(empty_backoff=(3.0, 8.0, 20.0))
        stream = Stream(id="s1", name="X", url="http://x/1")
        meta = {"has_video": True, "width": 1920, "height": 1080, "fps": 50.0,
               "video_codec": "h264", "video_profile": "", "pix_fmt": "yuv420p",
               "audio_codec": "aac", "audio_channels": 2,
               "video_variant_count": 1, "declared_kbps": 0,
               "container": "mpegts"}
        sleeps = []

        def fake_capture(*a, **k):
            return self._cap(decoded_seconds=10.9, measured_kbps=2608)

        with unittest.mock.patch.object(probe_mod, "probe_metadata", return_value=meta), \
             unittest.mock.patch.object(probe_mod, "capture", side_effect=fake_capture), \
             unittest.mock.patch.object(probe_mod.time, "sleep", sleeps.append):
            result = probe_mod.probe(stream, opts, "/tmp/t.jpg")

        self.assertEqual(sleeps, [1.5])
        self.assertNotIn("provider_declined", result)


class TestClipNeverCostsThePicture(Temp):
    """The real cause of a channel that played fine everywhere but failed
    every Diagnose and every re-probe.

    ffmpeg writes all of capture()'s outputs in ONE process. The clip is an
    optional extra, but an output it cannot even open aborts the entire
    command -- so an MP4 muxer rejecting the source's audio took the
    thumbnail, frame, crop and bitrate down with it, and the probe reported
    "no frame could be decoded" for a perfectly healthy stream. Verify runs
    were unaffected precisely because they capture no clip.
    """

    def test_clip_audio_is_transcoded_not_copied(self):
        # Fragmented MP4 writes its header up front, and the muxer cannot
        # describe an E-AC-3 track before parsing its packets -- so copying
        # eac3 in here fails with "Cannot write moov atom before EAC3
        # packets parsed" and kills every other output. Video must still be
        # a copy; that is where the cost would be.
        import unittest.mock
        from probarr import probe as probe_mod

        seen = []

        def fake_run(cmd, timeout):
            seen.append(cmd)
            raise RuntimeError("stop here")

        opts = probe_mod.ProbeOptions(capture_clip=True)
        with unittest.mock.patch.object(probe_mod, "_run", fake_run):
            try:
                probe_mod.capture("http://x/1", opts, "/tmp/t.jpg",
                                  "/tmp/f.jpg", "/tmp/c.jpg", "/tmp/clip.mp4")
            except RuntimeError:
                pass

        cmd = seen[0]
        self.assertIn("-c:a", cmd)
        self.assertEqual(cmd[cmd.index("-c:a") + 1], "aac")
        self.assertIn("-c:v", cmd)
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "copy")
        # The bare "-c copy" that used to cover BOTH tracks is what broke it.
        for i, tok in enumerate(cmd):
            if tok == "-c" and i + 1 < len(cmd) and cmd[i + 1] == "copy":
                # Only legitimate remaining use is the video-only bitrate remux.
                self.assertIn("mpegts", cmd[i:i + 6])

    def test_a_failed_clip_is_retried_without_the_clip(self):
        # General protection, independent of any one codec: if asking for a
        # clip produced no picture, try again without it before concluding
        # anything about the stream.
        import unittest.mock
        from probarr import probe as probe_mod
        from probarr.sources.base import Stream

        meta = {"has_video": True, "width": 1920, "height": 1080, "fps": 50.0,
               "video_codec": "hevc", "video_profile": "Main",
               "pix_fmt": "yuv420p", "audio_codec": "eac3", "audio_channels": 2,
               "video_variant_count": 1, "declared_kbps": 0,
               "container": "mpegts"}

        def blank(**over):
            cap = {"decode_errors": 3, "corruption_errors": 0,
                  "corruption_startup": 0, "corruption_steady": 0,
                  "corruption_per_sec": 0.0, "decoded_seconds": 0.0,
                  "error_samples": ["Could not write header"],
                  "capture_seconds": 2.0, "timed_out": False,
                  "rate_limited": False, "dhash": None, "motion": None,
                  "motion_frames": 0, "low_motion": False, "frame32": None,
                  "low_contrast": False, "measured_kbps": 0,
                  "sample_duration": 0.0, "thumb": None, "frame": None,
                  "crop": None, "clip": None}
            cap.update(over)
            return cap

        calls = []

        def fake_capture(url, opts, thumb, frame=None, crop=None, clip=None):
            calls.append(clip)
            if clip is not None:
                return blank()            # the clip output kills the command
            return blank(thumb="/tmp/t.jpg", decoded_seconds=10.0,
                        measured_kbps=2402, decode_errors=0)

        opts = probe_mod.ProbeOptions(capture_clip=True)
        stream = Stream(id="s1", name="HEVC FHD Comedy Central", url="http://x/1")
        with unittest.mock.patch.object(probe_mod, "probe_metadata", return_value=meta), \
             unittest.mock.patch.object(probe_mod, "capture", side_effect=fake_capture):
            result = probe_mod.probe(stream, opts, "/tmp/t.jpg", "/tmp/f.jpg",
                                     "/tmp/c.jpg", "/tmp/clip.mp4")

        self.assertEqual(calls, ["/tmp/clip.mp4", None])   # asked again, no clip
        self.assertEqual(result["status"], probe_mod.STATUS_OK)
        self.assertTrue(result.get("clip_skipped"))

    def test_the_clipless_retry_is_not_a_backoff_attempt(self):
        # A deterministic muxer failure fails identically every time, so
        # retrying the same broken command on a 3s/8s/20s backoff is pure
        # waste -- which is exactly what was observed in production (four
        # attempts over ~31s, all failing the same way). The clipless retry
        # must happen FIRST and immediately, with no sleep.
        import unittest.mock
        from probarr import probe as probe_mod
        from probarr.sources.base import Stream

        meta = {"has_video": True, "width": 1920, "height": 1080, "fps": 50.0,
               "video_codec": "hevc", "video_profile": "", "pix_fmt": "yuv420p",
               "audio_codec": "eac3", "audio_channels": 2,
               "video_variant_count": 1, "declared_kbps": 0,
               "container": "mpegts"}
        good = {"decode_errors": 0, "corruption_errors": 0,
               "corruption_startup": 0, "corruption_steady": 0,
               "corruption_per_sec": 0.0, "decoded_seconds": 10.0,
               "error_samples": [], "capture_seconds": 10.0, "timed_out": False,
               "rate_limited": False, "dhash": None, "motion": 5.0,
               "motion_frames": 20, "low_motion": False, "frame32": None,
               "low_contrast": False, "measured_kbps": 2402,
               "sample_duration": 10.0, "thumb": "/tmp/t.jpg", "frame": None,
               "crop": None, "clip": None}
        bad = {**good, "thumb": None, "decoded_seconds": 0.0,
              "measured_kbps": 0, "decode_errors": 3}

        sleeps = []

        def fake_capture(url, opts, thumb, frame=None, crop=None, clip=None):
            return dict(bad) if clip is not None else dict(good)

        opts = probe_mod.ProbeOptions(capture_clip=True)
        stream = Stream(id="s1", name="X", url="http://x/1")
        with unittest.mock.patch.object(probe_mod, "probe_metadata", return_value=meta), \
             unittest.mock.patch.object(probe_mod, "capture", side_effect=fake_capture), \
             unittest.mock.patch.object(probe_mod.time, "sleep", sleeps.append):
            result = probe_mod.probe(stream, opts, "/tmp/t.jpg", "/tmp/f.jpg",
                                     "/tmp/c.jpg", "/tmp/clip.mp4")

        self.assertEqual(sleeps, [], "must not back off before dropping the clip")
        self.assertEqual(result["status"], probe_mod.STATUS_OK)


class TestFiniteFilePlaceholder(unittest.TestCase):
    """A live channel's container should never report a finite duration --
    real IPTV sources overwhelmingly omit the field or return "N/A". A
    stream that answers with a real number is looping a finite file, most
    often the provider's own "channel unavailable" card. Complementary to
    annotate_placeholders()'s cross-channel still-picture matching (which
    needs the SAME frame on more than one channel): this needs no
    corroboration at all, so it catches a lone channel looping a file with
    no twin elsewhere in the lineup.
    """

    def test_parses_a_genuine_finite_duration(self):
        from probarr.probe import _parse_container_duration
        self.assertEqual(_parse_container_duration({"duration": "42.5"}), 42.5)

    def test_a_real_live_stream_reports_none_of_the_forms_ffprobe_uses(self):
        from probarr.probe import _parse_container_duration
        for fmt in ({}, {"duration": None}, {"duration": ""},
                   {"duration": "N/A"}, {"duration": "0"}, {"duration": "-1"},
                   {"duration": "not a number"}):
            self.assertIsNone(_parse_container_duration(fmt), fmt)

    def test_probe_flags_a_finite_duration_before_ever_capturing(self):
        # The whole point of catching this in probe_metadata() rather than
        # capture(): it must never spend the second, expensive decode
        # connection on a candidate already proven to be a finite loop.
        import unittest.mock
        from probarr import probe as probe_mod
        from probarr.sources.base import Stream

        fake_meta = {"has_video": True, "width": 1920, "height": 1080,
                    "fps": 50.0, "video_codec": "h264", "video_profile": "",
                    "pix_fmt": "yuv420p", "audio_codec": "aac",
                    "audio_channels": 2, "video_variant_count": 1,
                    "declared_kbps": 0, "container": "mpegts",
                    "container_duration": 12.3}
        opts = probe_mod.ProbeOptions()
        stream = Stream(id="s1", name="Holding Card", url="http://x/1")

        with unittest.mock.patch.object(probe_mod, "probe_metadata", return_value=fake_meta), \
             unittest.mock.patch.object(probe_mod, "capture") as fake_capture:
            result = probe_mod.probe(stream, opts, "/tmp/t.jpg")

        fake_capture.assert_not_called()
        self.assertEqual(result["status"], probe_mod.STATUS_PLACEHOLDER)
        self.assertIn("12.3s", result["reason"])

    def test_probe_does_not_flag_a_stream_with_no_declared_duration(self):
        import unittest.mock
        from probarr import probe as probe_mod
        from probarr.sources.base import Stream

        fake_meta = {"has_video": True, "width": 1920, "height": 1080,
                    "fps": 50.0, "video_codec": "h264", "video_profile": "",
                    "pix_fmt": "yuv420p", "audio_codec": "aac",
                    "audio_channels": 2, "video_variant_count": 1,
                    "declared_kbps": 0, "container": "mpegts",
                    "container_duration": None}
        fake_cap = {"thumb": "/tmp/t.jpg", "decode_errors": 0,
                   "corruption_errors": 0, "corruption_startup": 0,
                   "corruption_steady": 0, "corruption_per_sec": 0.0,
                   "decoded_seconds": 10.0, "error_samples": [],
                   "capture_seconds": 10.0, "timed_out": False,
                   "rate_limited": False, "dhash": None, "motion": None,
                   "motion_frames": 0, "low_motion": False, "frame32": None,
                   "low_contrast": False, "measured_kbps": 1000,
                   "sample_duration": 10.0, "frame": None, "crop": None,
                   "clip": None}
        opts = probe_mod.ProbeOptions()
        stream = Stream(id="s1", name="Real Channel", url="http://x/1")

        with unittest.mock.patch.object(probe_mod, "probe_metadata", return_value=fake_meta), \
             unittest.mock.patch.object(probe_mod, "capture", return_value=fake_cap) as fake_capture:
            result = probe_mod.probe(stream, opts, "/tmp/t.jpg")

        fake_capture.assert_called_once()
        self.assertEqual(result["status"], probe_mod.STATUS_OK)


class TestReprobeSampleLength(Temp):
    """A plain single ↻ re-probe used to inherit the full unattended-Verify
    sample length (cfg["sample_seconds"], 8-10s by default) -- a leftover
    from before the standalone Preview button (short, 6s) was merged into
    it. The merge kept the clip capture but never picked up Preview's short
    window. A ↻ click is always attended -- a human is about to look at the
    resulting frame -- and the corruption-rate math a long unattended
    sample exists for isn't what that click needs.
    """

    def test_plain_reprobe_uses_the_short_window_not_the_bulk_default(self):
        import unittest.mock
        from probarr import web as web_mod
        from probarr.store import RunStore

        store = RunStore(self.root, "run1")
        store.append({"rec_key": "C1|s1", "channel_key": "C1", "stream_id": "s1",
                      "stream_name": "X", "url": "http://x/1", "url_redacted": "",
                      "group": "", "logo": "", "tvg_id": "", "probed_at": 1})

        seen_opts = []

        def fake_probe(stream, opts, *a, **k):
            seen_opts.append(opts)
            return {"status": "ok"}

        with unittest.mock.patch.object(web_mod, "probe", fake_probe), \
             unittest.mock.patch.object(web_mod.ProbeOptions, "resolved", lambda self: self), \
             unittest.mock.patch.object(web_mod, "settings_mod") as settings_mock:
            settings_mock.read.return_value = {
                "sample_seconds": 10,   # the BULK/Verify default -- must NOT be used
                "frame_height": 720, "thumb_height": 240}
            web_mod.Handler.root = self.root
            result = web_mod.Handler._run_reprobe(
                {"run_id": "run1", "rec_key": "C1|s1"})

        self.assertNotIn("error", result)
        self.assertEqual(len(seen_opts), 1)
        self.assertEqual(seen_opts[0].sample_seconds,
                         web_mod.Handler.REPROBE_SAMPLE_SECONDS)
        self.assertEqual(seen_opts[0].sample_seconds,
                         web_mod.Handler.PREVIEW_SAMPLE_SECONDS)
        self.assertNotEqual(seen_opts[0].sample_seconds, 10,
                            "plain re-probe must not use the bulk-verify sample length")

    def test_diagnose_still_uses_its_own_longer_window(self):
        import unittest.mock
        from probarr import web as web_mod
        from probarr.store import RunStore

        store = RunStore(self.root, "run1")
        store.append({"rec_key": "C1|s1", "channel_key": "C1", "stream_id": "s1",
                      "stream_name": "X", "url": "http://x/1", "url_redacted": "",
                      "group": "", "logo": "", "tvg_id": "", "probed_at": 1})

        seen_opts = []

        def fake_probe(stream, opts, *a, **k):
            seen_opts.append(opts)
            return {"status": "ok"}

        with unittest.mock.patch.object(web_mod, "probe", fake_probe), \
             unittest.mock.patch.object(web_mod.ProbeOptions, "resolved", lambda self: self), \
             unittest.mock.patch.object(web_mod, "settings_mod") as settings_mock:
            settings_mock.read.return_value = {
                "sample_seconds": 10, "frame_height": 720, "thumb_height": 240}
            web_mod.Handler.root = self.root
            web_mod.Handler._run_reprobe(
                {"run_id": "run1", "rec_key": "C1|s1", "diagnose": True})

        self.assertEqual(seen_opts[0].sample_seconds,
                         web_mod.Handler.DIAGNOSE_SAMPLE_SECONDS)


class TestStreamUrlMapPrefersNative(unittest.TestCase):
    """The other half of the per-provider-accounts story, found while
    verifying the enforcement fix above against real data: a channel
    pushed BEFORE its provider had a correctly configured Dispatcharr
    account keeps an old custom stream around. Once the account is fixed
    and Dispatcharr's own refresh produces a NATIVE stream with the
    identical URL, get_or_create_custom_stream()'s lookup must always
    prefer that native one -- not whichever happened to paginate last.
    Confirmed live: one real channel's four candidates split 3 custom / 1
    native despite all four existing natively by push time, purely from
    dict-comprehension pagination order.
    """

    def _client(self, streams):
        from probarr.sources.dispatcharr import Dispatcharr
        c = Dispatcharr("http://x", "u", "p")
        c.api = lambda method, path, body=None: None
        c.paged = lambda path, page_size=1000: streams
        return c

    def test_native_wins_when_native_is_paginated_first(self):
        client = self._client([
            {"id": 100, "url": "http://p/1", "is_custom": False},
            {"id": 200, "url": "http://p/1", "is_custom": True},
        ])
        self.assertEqual(client.stream_url_map()["http://p/1"], 100)

    def test_native_wins_when_custom_is_paginated_first(self):
        # The order that actually broke it live -- the stale custom row
        # happened to come later in pagination than the fresh native one.
        client = self._client([
            {"id": 200, "url": "http://p/1", "is_custom": True},
            {"id": 100, "url": "http://p/1", "is_custom": False},
        ])
        self.assertEqual(client.stream_url_map()["http://p/1"], 100)

    def test_a_url_that_only_exists_as_custom_still_resolves(self):
        client = self._client([{"id": 200, "url": "http://p/1", "is_custom": True}])
        self.assertEqual(client.stream_url_map()["http://p/1"], 200)

    def test_streams_with_no_url_are_skipped_not_crashed_on(self):
        client = self._client([
            {"id": 1, "url": None, "is_custom": False},
            {"id": 2, "url": "http://p/1", "is_custom": False},
        ])
        self.assertEqual(client.stream_url_map(), {"http://p/1": 2})


class TestPerProviderStreamLimit(unittest.TestCase):
    """docs/design/per-provider-m3u-accounts.md's first real piece: once a
    provider has a real Dispatcharr M3U account (not the shared "custom"
    one), that account's own max_streams should be kept in step too --
    it's what Dispatcharr enforces against Live TV AND VOD together, which
    the shared account's limit never could.
    """

    def _client(self, accounts, patches=None):
        from probarr.sources.dispatcharr import Dispatcharr
        c = Dispatcharr("http://x", "u", "p")
        calls = []

        def fake_api(method, path, body=None):
            calls.append((method, path, body))
            if method == "GET" and path == "/api/m3u/accounts/":
                return accounts
            if method == "PATCH":
                acct_id = int(path.strip("/").split("/")[-1])
                acct = next(a for a in accounts if a["id"] == acct_id)
                acct.update(body)
                return acct
            raise AssertionError(f"unexpected call {method} {path}")

        c.api = fake_api
        return c, calls

    def test_finds_account_by_exact_server_url_only(self):
        accounts = [
            {"id": 1, "name": "custom", "server_url": None, "max_streams": 0},
            {"id": 10, "name": "BunnyCustom",
             "server_url": "https://mybunny.tv/client/download.php?u=phgegfxn&p=BmUXAWZPUaQF",  # probarr:allow-secret
             "max_streams": 4},
        ]
        client, _ = self._client(accounts)
        found = client.find_account_for_source(
            "https://mybunny.tv/client/download.php?u=phgegfxn&p=BmUXAWZPUaQF")  # probarr:allow-secret
        self.assertEqual(found["id"], 10)

        # A near-miss (different credentials) must NOT match -- exact
        # equality only, never a same-host guess.
        self.assertIsNone(client.find_account_for_source(
            "https://mybunny.tv/client/download.php?u=someoneelse&p=x"))  # probarr:allow-secret

    def test_enforce_provider_stream_limit_tightens_the_real_account(self):
        accounts = [{"id": 10, "name": "BunnyCustom",
                     "server_url": "https://p.tv/m3u", "max_streams": 8}]
        client, calls = self._client(accounts)
        client.enforce_provider_stream_limit("https://p.tv/m3u", 4)
        self.assertEqual(accounts[0]["max_streams"], 4)
        self.assertTrue(any(m == "PATCH" for m, *_ in calls))

    def test_enforce_provider_stream_limit_never_raises_it(self):
        accounts = [{"id": 10, "name": "BunnyCustom",
                     "server_url": "https://p.tv/m3u", "max_streams": 2}]
        client, calls = self._client(accounts)
        client.enforce_provider_stream_limit("https://p.tv/m3u", 6)
        self.assertEqual(accounts[0]["max_streams"], 2)   # unchanged
        self.assertFalse(any(m == "PATCH" for m, *_ in calls))

    def test_enforce_provider_stream_limit_is_a_noop_with_no_matching_account(self):
        accounts = [{"id": 1, "name": "custom", "server_url": None, "max_streams": 0}]
        client, calls = self._client(accounts)
        client.enforce_provider_stream_limit("https://p.tv/m3u", 4)
        self.assertFalse(any(m == "PATCH" for m, *_ in calls))

    def test_enforce_provider_stream_limit_ignores_a_non_positive_limit(self):
        accounts = [{"id": 10, "name": "BunnyCustom",
                     "server_url": "https://p.tv/m3u", "max_streams": 8}]
        client, calls = self._client(accounts)
        client.enforce_provider_stream_limit("https://p.tv/m3u", 0)
        client.enforce_provider_stream_limit("https://p.tv/m3u", None)
        self.assertFalse(any(m == "PATCH" for m, *_ in calls))

    def test_shared_custom_account_and_real_account_are_independent(self):
        # Both get tightened on a push, to their own separate values --
        # tightening one must not touch the other.
        accounts = [
            {"id": 1, "name": "custom", "server_url": None, "max_streams": 0},
            {"id": 10, "name": "BunnyCustom",
             "server_url": "https://p.tv/m3u", "max_streams": 8},
        ]
        client, _ = self._client(accounts)
        client.enforce_custom_stream_limit(4)
        client.enforce_provider_stream_limit("https://p.tv/m3u", 4)
        self.assertEqual(accounts[0]["max_streams"], 4)
        self.assertEqual(accounts[1]["max_streams"], 4)

    def test_find_account_for_source_never_matches_a_falsy_spec(self):
        # server_url: None on the shared "custom" account must never be
        # treated as a match for "no spec known" -- see
        # find_account_for_source()'s docstring.
        accounts = [{"id": 1, "name": "custom", "server_url": None, "max_streams": 0}]
        client, calls = self._client(accounts)
        self.assertIsNone(client.find_account_for_source(None))
        self.assertIsNone(client.find_account_for_source(""))
        self.assertFalse(calls)  # short-circuited before ever hitting the API

    def test_enforce_provider_stream_limit_with_no_spec_is_a_noop(self):
        accounts = [{"id": 1, "name": "custom", "server_url": None, "max_streams": 0}]
        client, calls = self._client(accounts)
        client.enforce_provider_stream_limit(None, 4)
        self.assertFalse(any(m == "PATCH" for m, *_ in calls))


class TestGetOrCreateAccountForSource(unittest.TestCase):
    """The automated version of docs/design/per-provider-m3u-accounts.md's
    "step zero" -- creating the real Dispatcharr M3U account a provider
    needs, instead of that being a manual, by-hand prerequisite.
    """

    def _client(self, accounts):
        from probarr.sources.dispatcharr import Dispatcharr
        c = Dispatcharr("http://x", "u", "p")
        calls = []
        created = []

        def fake_api(method, path, body=None):
            calls.append((method, path, body))
            if method == "GET" and path == "/api/m3u/accounts/":
                return accounts
            if method == "POST" and path == "/api/m3u/accounts/":
                acct = {"id": 99, **body}
                created.append(acct)
                accounts.append(acct)
                return acct
            raise AssertionError(f"unexpected call {method} {path}")

        c.api = fake_api
        return c, calls, created

    def test_creates_an_account_when_none_matches(self):
        client, calls, created = self._client([])
        acct = client.get_or_create_account_for_source("https://p.tv/m3u", "mybunny")
        self.assertEqual(acct["id"], 99)
        self.assertEqual(created[0]["server_url"], "https://p.tv/m3u")
        self.assertEqual(created[0]["name"], "mybunny")

    def test_reuses_an_existing_matching_account_without_creating(self):
        accounts = [{"id": 10, "name": "BunnyCustom",
                     "server_url": "https://p.tv/m3u", "max_streams": 8}]
        client, calls, created = self._client(accounts)
        acct = client.get_or_create_account_for_source("https://p.tv/m3u", "mybunny")
        self.assertEqual(acct["id"], 10)
        self.assertFalse(created)
        self.assertFalse(any(m == "POST" for m, *_ in calls))

    def test_skips_a_non_url_spec_entirely(self):
        # dispatcharr:// and xtream:// specs have no server_url string a
        # real M3U account could ever match verbatim -- no-op, not a guess.
        client, calls, created = self._client([])
        self.assertIsNone(
            client.get_or_create_account_for_source("dispatcharr://u:p@host:9191",
                                                     "mydispatch"))
        self.assertIsNone(
            client.get_or_create_account_for_source("xtream://u:p@host:8080", "myx"))
        self.assertFalse(calls)
        self.assertFalse(created)

    def test_skips_an_empty_spec(self):
        client, calls, created = self._client([])
        self.assertIsNone(client.get_or_create_account_for_source(None, "mybunny"))
        self.assertIsNone(client.get_or_create_account_for_source("", "mybunny"))
        self.assertFalse(calls)

    def test_a_create_failure_is_logged_not_raised(self):
        from probarr import http
        client, _, _ = self._client([])

        def failing_api(method, path, body=None):
            if method == "GET" and path == "/api/m3u/accounts/":
                return []
            raise http.HttpError(500, "boom")

        client.api = failing_api
        logged = []
        result = client.get_or_create_account_for_source(
            "https://p.tv/m3u", "mybunny", log=logged.append)
        self.assertIsNone(result)
        self.assertTrue(logged)


class TestRunExportUsesTheSourceProviderSpec(Temp):
    """web.py's _run_export() used to pass `prov["spec"]` -- the DISPATCHARR
    connection being pushed INTO -- to enforce_provider_stream_limit() and
    get_or_create_account_for_source(), both of which match against the
    ORIGINAL upstream provider's own spec (e.g. mybunny's playlist URL).
    A dispatcharr:// spec can never equal a real M3U account's server_url,
    so that call was silently always a no-op. This exercises the fix: the
    saved SOURCE provider's spec (looked up via meta["provider_name"]) is
    what actually gets passed.
    """

    def _run(self, create_account):
        from probarr import web as web_mod, providers as providers_mod
        from probarr.store import RunStore

        providers_mod.save(self.root, "mybunny", "https://p.tv/m3u?u=x&p=y")
        providers_mod.save(self.root, "mydispatch", "dispatcharr://u:p@host:9191")

        store = RunStore(self.root, "run1")
        store.write_meta({"provider_name": "mybunny", "source": "https://p.tv/m3u",
                          "concurrency": 2})
        store.write_push_status({"state": "running", "phase": "resolving",
                                 "done": 0, "total": 0, "started": 0})

        web_mod.Handler.root = self.root
        handler = web_mod.Handler.__new__(web_mod.Handler)

        fake_client = unittest.mock.MagicMock()
        prov = {"name": "mydispatch", "spec": "dispatcharr://u:p@host:9191"}

        with unittest.mock.patch.object(web_mod, "client_from_spec",
                                        return_value=fake_client), \
             unittest.mock.patch.object(handler, "_forget_remote_groups"), \
             unittest.mock.patch.object(handler, "_apply_removals", return_value=[]), \
             unittest.mock.patch.object(handler, "_resolve_epg_overrides",
                                        return_value=({}, set())), \
             unittest.mock.patch.object(web_mod, "dispatcharr_export") as fake_export:
            fake_export.push.return_value = {}
            handler._run_export(store, prov, "mydispatch", [], "native",
                               None, "probarr", prune_empty=True,
                               apply_removals=False, create_account=create_account)

        return fake_client

    def test_enforce_provider_stream_limit_gets_the_source_spec_not_the_target(self):
        client = self._run(create_account=False)
        client.enforce_provider_stream_limit.assert_called_once_with(
            "https://p.tv/m3u?u=x&p=y", 2, log=unittest.mock.ANY)
        client.get_or_create_account_for_source.assert_not_called()

    def test_create_account_opt_in_also_uses_the_source_spec(self):
        client = self._run(create_account=True)
        client.get_or_create_account_for_source.assert_called_once_with(
            "https://p.tv/m3u?u=x&p=y", "mybunny", log=unittest.mock.ANY)


class TestDispatcharrEpgSources(Temp):
    """Real usability request: the Setup Wizard's EPG step forced someone
    whose channels came from Dispatcharr to either skip it or hunt down an
    XMLTV URL by hand, even though Dispatcharr already has one (or several)
    configured -- /api/dispatcharr-epg-sources reads them directly.
    """

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: (
            sent.append((code, body)), sent)[-1]
        return h, web_mod, sent

    def test_lists_the_provider_s_configured_sources(self):
        providers.save(self.root, "mydispatch", "dispatcharr://u:p@host:9191")
        handler, web_mod, sent = self._handler()
        fake_client = unittest.mock.MagicMock()
        fake_client.list_epg_sources.return_value = [
            {"name": "open-epg", "url": "https://x/uk.xml", "has_channels": True},
            {"name": "unused", "url": "https://x/unused.xml", "has_channels": False},
        ]
        with unittest.mock.patch.object(web_mod, "client_from_spec",
                                        return_value=fake_client):
            handler._dispatcharr_epg_sources({"provider": "mydispatch"})
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        out = json.loads(body)["epg_sources"]
        self.assertEqual(len(out), 2)
        by_name = {s["name"]: s for s in out}
        self.assertEqual(by_name["open-epg"]["url"], "https://x/uk.xml")
        self.assertTrue(by_name["open-epg"]["has_channels"])
        self.assertFalse(by_name["unused"]["has_channels"])

    def test_rejects_a_non_dispatcharr_provider(self):
        providers.save(self.root, "mybunny", "https://p.tv/m3u?u=x&p=y")
        handler, web_mod, sent = self._handler()
        handler._dispatcharr_epg_sources({"provider": "mybunny"})
        self.assertEqual(sent[-1][0], 404)

    def test_reports_a_dispatcharr_error_without_crashing(self):
        providers.save(self.root, "mydispatch", "dispatcharr://u:p@host:9191")
        handler, web_mod, sent = self._handler()
        fake_client = unittest.mock.MagicMock()
        fake_client.list_epg_sources.side_effect = RuntimeError("boom")
        with unittest.mock.patch.object(web_mod, "client_from_spec",
                                        return_value=fake_client):
            handler._dispatcharr_epg_sources({"provider": "mydispatch"})
        self.assertEqual(sent[-1][0], 502)


class TestBrowseDispatcharrActiveLineup(Temp):
    """probarr-oz2: Browse Channels for a dispatcharr:// provider used to
    always show every raw stream Dispatcharr has ever ingested from any M3U
    account (tens of thousands on a real instance) instead of the operator's
    actual curated lineup. `active_only` opts into the curated view -- one
    row per Dispatcharr channel, with its real category as `group` -- and is
    silently ignored for any non-dispatcharr provider.
    """

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        return h, web_mod

    def test_active_only_uses_curated_lineup_not_raw_streams(self):
        providers.save(self.root, "mydispatch", "dispatcharr://u:p@host:9191")
        handler, web_mod = self._handler()

        fake_client = unittest.mock.MagicMock()
        fake_client.active_lineup.return_value = [
            {"id": 1, "name": "Beyond Paradise", "group": "Niko TV", "tvg_id": ""},
            {"id": 2, "name": "24/7 Eureka", "group": "24/7", "tvg_id": ""},
        ]

        with unittest.mock.patch.object(web_mod, "client_from_spec",
                                        return_value=fake_client), \
             unittest.mock.patch.object(web_mod, "load_source") as fake_load, \
             unittest.mock.patch.object(handler, "_send") as fake_send:
            handler._browse({"provider": "mydispatch", "active_only": True})

        fake_load.assert_not_called()
        fake_client.active_lineup.assert_called_once()
        body = json.loads(fake_send.call_args[0][0])
        self.assertEqual(len(body["channels"]), 2)
        self.assertEqual(body["total_streams"], 2)
        self.assertEqual(sorted(body["groups"]), ["24/7", "Niko TV"])
        names = {c["name"]: c["group"] for c in body["channels"]}
        self.assertEqual(names["Beyond Paradise"], "Niko TV")

    def test_active_only_carries_the_channel_number_and_tvg_id_through(self):
        """Real usability bug: pulling Dispatcharr's channels into the Setup
        Wizard's wantlist used to drop the number entirely -- a channel
        imported that way sat unnumbered (dropped from every export) until
        someone noticed and set it by hand in Curate. active_lineup() (and
        this endpoint's passthrough of it) must carry both the number and
        the tvg_id, not just name/group.
        """
        providers.save(self.root, "mydispatch", "dispatcharr://u:p@host:9191")
        handler, web_mod = self._handler()
        fake_client = unittest.mock.MagicMock()
        fake_client.active_lineup.return_value = [
            {"id": 1, "name": "BBC One", "group": "Free to air",
             "tvg_id": "bbcone.uk", "number": 101},
            {"id": 2, "name": "No Number Yet", "group": "", "tvg_id": "", "number": None},
        ]
        with unittest.mock.patch.object(web_mod, "client_from_spec",
                                        return_value=fake_client), \
             unittest.mock.patch.object(web_mod, "load_source"), \
             unittest.mock.patch.object(handler, "_send") as fake_send:
            handler._browse({"provider": "mydispatch", "active_only": True})
        body = json.loads(fake_send.call_args[0][0])
        by_name = {c["name"]: c for c in body["channels"]}
        self.assertEqual(by_name["BBC One"]["number"], 101)
        self.assertEqual(by_name["BBC One"]["tvg_id"], "bbcone.uk")
        self.assertIsNone(by_name["No Number Yet"]["number"])

    def test_active_only_ignored_for_non_dispatcharr_provider(self):
        providers.save(self.root, "mybunny", "https://p.tv/m3u?u=x&p=y")
        handler, web_mod = self._handler()

        from probarr.sources.base import Stream
        streams = [Stream(id="1", name="BBC One", url="http://x/1", group="",
                          logo="", tvg_id="", source="mybunny", attrs={})]

        with unittest.mock.patch.object(web_mod, "load_source",
                                        return_value=streams) as fake_load, \
             unittest.mock.patch.object(web_mod, "client_from_spec") as fake_client_from_spec, \
             unittest.mock.patch.object(handler, "_send") as fake_send:
            handler._browse({"provider": "mybunny", "active_only": True})

        fake_load.assert_called_once()
        fake_client_from_spec.assert_not_called()
        body = json.loads(fake_send.call_args[0][0])
        self.assertEqual(body["total_streams"], 1)

    def test_dispatcharr_error_surfaces_as_502(self):
        providers.save(self.root, "mydispatch", "dispatcharr://u:p@host:9191")
        handler, web_mod = self._handler()

        with unittest.mock.patch.object(web_mod, "client_from_spec",
                                        side_effect=RuntimeError("unreachable")), \
             unittest.mock.patch.object(handler, "_send") as fake_send:
            handler._browse({"provider": "mydispatch", "active_only": True})

        args, kwargs = fake_send.call_args
        status = args[2] if len(args) > 2 else kwargs.get("status")
        self.assertEqual(status, 502)


class TestReferenceLineups(Temp):
    def _fake_response(self, payload):
        body = json.dumps(payload).encode()
        cm = unittest.mock.MagicMock()
        cm.__enter__.return_value.read.return_value = body
        return cm

    def test_discovers_and_caches_the_repo_listing(self):
        listing = [{"name": "UK_SkyTV_lineup.json"}, {"name": "plugin.json"}]
        with unittest.mock.patch("probarr.wantlist.urllib.request.urlopen",
                                  return_value=self._fake_response(listing)) as m:
            items = wl.known_reference_lineups(self.root)
            self.assertEqual(len(items), 1)   # plugin.json excluded
            self.assertEqual(items[0]["region"], "United Kingdom")
            m.assert_called_once()
            # Second call must hit the on-disk cache, not fetch again.
            wl.known_reference_lineups(self.root)
            m.assert_called_once()

    def test_refresh_forces_a_new_fetch(self):
        with unittest.mock.patch("probarr.wantlist.urllib.request.urlopen",
                                  return_value=self._fake_response([])) as m:
            wl.known_reference_lineups(self.root)
            wl.known_reference_lineups(self.root, force=True)
            self.assertEqual(m.call_count, 2)


class TestRank(unittest.TestCase):
    def test_a_bigger_picture_beats_a_cleaner_log(self):
        # Changed deliberately from the opposite rule. Streams logging decode
        # errors play fine -- the decoder conceals them -- so preferring a
        # 1.1 Mbps 576p stream over a 5 Mbps 1080p one because the first
        # logged nothing produced a visibly worse picture in real viewing.
        dirty_but_big = {"status": "dirty", "width": 1920, "height": 1080,
                         "fps": 50, "measured_kbps": 5000,
                         "corruption_errors": 67, "corruption_per_sec": 6.7}
        clean_but_small = {"status": "ok", "width": 720, "height": 576,
                           "fps": 50, "measured_kbps": 1144,
                           "corruption_errors": 0, "corruption_per_sec": 0}
        self.assertIs(rank([clean_but_small, dirty_but_big])[0], dirty_but_big)

    def test_bitrate_beats_frame_rate_at_the_same_size(self):
        smooth = {"status": "ok", "width": 1920, "height": 1080, "fps": 50,
                  "measured_kbps": 1588}
        detailed = {"status": "ok", "width": 1920, "height": 1080, "fps": 25,
                    "measured_kbps": 5792}
        self.assertIs(rank([smooth, detailed])[0], detailed)

    def test_frame_rate_still_decides_between_equals(self):
        slow = {"status": "ok", "width": 1920, "height": 1080, "fps": 25,
                "measured_kbps": 5000}
        fast = {"status": "ok", "width": 1920, "height": 1080, "fps": 50,
                "measured_kbps": 5000}
        self.assertIs(rank([slow, fast])[0], fast)

    def test_a_small_bitrate_difference_does_not_decide_the_winner(self):
        """Real complaint: the "Changed" alert kept firing "X now ranks above
        your pick" between one re-verify and the next with no real
        difference in either stream. The actual cause was this exact sort
        term comparing raw measured_kbps -- a single live feed's bitrate
        moves with what's on screen (busy action vs a static shot), so two
        probes of the SAME stream a few seconds apart were never going to
        report identical numbers. A close difference must fall through to
        the next real tiebreaker (here, frame rate) instead of deciding it.
        """
        slightly_lower_but_smoother = {"status": "ok", "width": 1920, "height": 1080,
                                       "fps": 50, "measured_kbps": 4800}
        slightly_higher_but_choppier = {"status": "ok", "width": 1920, "height": 1080,
                                        "fps": 25, "measured_kbps": 5000}
        self.assertIs(rank([slightly_higher_but_choppier,
                            slightly_lower_but_smoother])[0],
                      slightly_lower_but_smoother,
                      "a ~4% bitrate difference must not outrank double the frame rate")

    def test_a_real_bitrate_difference_still_decides_the_winner(self):
        clearly_better = {"status": "ok", "width": 1920, "height": 1080,
                          "fps": 25, "measured_kbps": 8000}
        clearly_worse = {"status": "ok", "width": 1920, "height": 1080,
                         "fps": 25, "measured_kbps": 2000}
        self.assertIs(rank([clearly_worse, clearly_better])[0], clearly_better)

    def test_errors_break_a_tie_between_equals(self):
        a = {"status": "dirty", "width": 1920, "height": 1080, "fps": 25,
             "measured_kbps": 4000, "corruption_per_sec": 9.0}
        b = {"status": "ok", "width": 1920, "height": 1080, "fps": 25,
             "measured_kbps": 4000, "corruption_per_sec": 0.0}
        self.assertIs(rank([a, b])[0], b)

    def test_unplayable_still_ranks_below_everything_that_plays(self):
        for bad in ({"status": "dead"}, {"status": "no_frame"},
                    {"status": "placeholder", "width": 1920, "height": 1080,
                     "fps": 50, "measured_kbps": 9000}):
            plays = {"status": "dirty", "width": 640, "height": 360, "fps": 25,
                     "measured_kbps": 500, "corruption_per_sec": 20}
            self.assertIs(rank([bad, plays])[0], plays, bad["status"])

    def test_dead_streams_rank_last(self):
        dead = {"status": "dead", "width": 0, "height": 0}
        ok = {"status": "ok", "width": 1280, "height": 720, "fps": 25,
              "measured_kbps": 2000, "corruption_errors": 0}
        self.assertIs(rank([dead, ok])[0], ok)


class TestM3UExport(unittest.TestCase, ):
    def test_export_carries_group_logo_and_tvg_id(self):
        # The regression: exports named every channel and matched none of
        # them to a guide, with no icons either.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.m3u")
            m3u.write([(101, "BBC One", "General", "http://logo/1.png",
                        "bbc.one.uk", "http://stream/1")], path)
            with open(path) as f:
                text = f.read()
        self.assertIn('tvg-chno="101"', text)
        self.assertIn('group-title="General"', text)
        self.assertIn('tvg-logo="http://logo/1.png"', text)
        self.assertIn('tvg-id="bbc.one.uk"', text)

    def test_round_trips_through_the_parser(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.m3u")
            m3u.write([(1, "Chan One", "G", "", "", "http://s/1")], path)
            back = m3u.load(path)
        self.assertEqual(back[0].name, "Chan One")
        self.assertEqual(back[0].url, "http://s/1")

    def test_a_missing_local_file_gives_an_actionable_error_not_a_bare_oserror(self):
        """Real reported case: a run's local M3U source pointed at
        '/config/uk-fta-snapshot.m3u', which existed on the host but
        outside either container's own mounted config directory (test
        and production use separate ./probarr/config and
        ./probarr-vpn/config mounts) -- so it 404'd inside the container.
        The error that reached the UI was a bare "[Errno 2] No such file
        or directory: '/config/uk-fta-snapshot.m3u'", which explains
        nothing about WHY a file the operator can see on the host isn't
        visible to probarr. The message must at least point at the real,
        actual cause (a container-local path, not a host path).
        """
        with self.assertRaises(ValueError) as ctx:
            m3u.load("/config/does-not-exist.m3u")
        msg = str(ctx.exception)
        self.assertIn("does-not-exist.m3u", msg)
        self.assertIn("container", msg)


class TestDispatcharrProxyCandidates(unittest.TestCase):
    """Real request: an install where probarr itself doesn't have the
    network path (VPN, geo-IP) a provider needs, but Dispatcharr already
    does. proxy_candidate_streams() adds one candidate per already-
    assigned channel that routes through Dispatcharr's OWN proxy instead
    of the raw upstream URL -- see sources/dispatcharr.py's load()."""

    def _client(self, channels):
        from probarr.sources.dispatcharr import Dispatcharr
        client = Dispatcharr("http://fake:9191", "u", "p")
        client.channels = lambda: channels
        return client

    def test_one_candidate_per_channel_with_a_stream_assigned(self):
        client = self._client([
            {"id": 1, "uuid": "aaa", "name": "BBC One", "streams": [10],
             "tvg_id": "", "logo_url": ""},
            {"id": 2, "uuid": "bbb", "name": "Empty Channel", "streams": [],
             "tvg_id": "", "logo_url": ""},
            {"id": 3, "uuid": None, "name": "No UUID", "streams": [11],
             "tvg_id": "", "logo_url": ""},
        ])
        out = client.proxy_candidate_streams()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].id, "dispatcharr-proxy:aaa")
        self.assertIn("BBC One", out[0].name)
        self.assertIn("via Dispatcharr", out[0].name)
        self.assertEqual(out[0].url, "http://fake:9191/proxy/ts/stream/aaa")

    def test_the_display_suffix_is_stripped_for_matching_but_kept_for_display(self):
        """The "(via Dispatcharr)" suffix must fold to the SAME normalised
        key as the plain channel name -- Normalizer's bracket-stripping
        does this automatically, but it's exactly the kind of thing that
        silently breaks if the format string ever loses its parentheses."""
        from probarr.normalize import Normalizer
        client = self._client([
            {"id": 1, "uuid": "aaa", "name": "BBC One", "streams": [10],
             "tvg_id": "", "logo_url": ""},
        ])
        proxy_candidate = client.proxy_candidate_streams()[0]
        n = Normalizer()
        self.assertEqual(n.key(proxy_candidate.name), n.key("BBC One"))

    def test_load_with_prefer_proxy_merges_raw_and_proxy_candidates(self):
        from probarr.sources import dispatcharr as dispatcharr_mod
        fake_raw = [object()]
        fake_proxy = [object(), object()]

        class FakeClient:
            def streams(self): return fake_raw
            def proxy_candidate_streams(self): return fake_proxy

        with unittest.mock.patch.object(dispatcharr_mod, "client_from_spec",
                                        return_value=FakeClient()):
            out = dispatcharr_mod.load("dispatcharr://u:p@h:9191", prefer_proxy=True)
        self.assertEqual(out, fake_raw + fake_proxy)

    def test_load_without_prefer_proxy_is_unchanged(self):
        from probarr.sources import dispatcharr as dispatcharr_mod
        fake_raw = [object()]

        class FakeClient:
            def streams(self): return fake_raw
            def proxy_candidate_streams(self):
                raise AssertionError("must not be called when prefer_proxy is off")

        with unittest.mock.patch.object(dispatcharr_mod, "client_from_spec",
                                        return_value=FakeClient()):
            out = dispatcharr_mod.load("dispatcharr://u:p@h:9191")
        self.assertEqual(out, fake_raw)


class TestExpand(unittest.TestCase):
    """_expand() -- the ordered-streams shape a push actually writes."""

    def test_native_mode_sends_the_whole_ordered_list(self):
        from probarr.dispatcharr_export import _expand
        ch = {"number": 101, "name": "Ch", "primary": {"stream_id": 1},
              "fallback": {"stream_id": 2},
              "streams": [{"stream_id": 1}, {"stream_id": 2}, {"stream_id": 3}]}
        rows = _expand([ch], "native")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], [1, 2, 3])

    def test_native_mode_falls_back_to_primary_fallback_with_no_list(self):
        from probarr.dispatcharr_export import _expand
        ch = {"number": 101, "name": "Ch", "primary": {"stream_id": 1},
              "fallback": {"stream_id": 2}}
        rows = _expand([ch], "native")
        self.assertEqual(rows[0][3], [1, 2])

    def test_separate_mode_ignores_a_third_stream(self):
        from probarr.dispatcharr_export import _expand
        ch = {"number": 101, "name": "Ch", "primary": {"stream_id": 1},
              "fallback": {"stream_id": 2},
              "streams": [{"stream_id": 1}, {"stream_id": 2}, {"stream_id": 3}]}
        rows = _expand([ch], "separate")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][3], [1])
        self.assertEqual(rows[1][3], [2])
        self.assertEqual(rows[1][2], "FALLBACK: Ch")


class FakeDispatcharrClient:
    """Just enough of sources/dispatcharr.py's Dispatcharr to drive plan()
    and push() without a real server -- an in-memory Logo/Group/Channel
    table plus the handful of methods dispatcharr_export.py actually calls.
    """

    def __init__(self, existing_channels=None, existing_logos=None,
                existing_groups=None):
        self._channels = list(existing_channels or [])
        self._logos = list(existing_logos or [])
        self._groups = list(existing_groups or [])
        self._next_id = 1000
        self.created_logos = []   # (name, url) actually POSTed, in order

    def _id(self):
        self._next_id += 1
        return self._next_id

    def channels(self):
        return self._channels

    def logos(self):
        return self._logos

    def groups(self):
        return self._groups

    def get_or_create_group(self, name):
        for g in self._groups:
            if g.get("name", "").strip().lower() == name.strip().lower():
                return g["id"]
        gid = self._id()
        self._groups.append({"id": gid, "name": name})
        return gid

    def get_or_create_logo(self, name, url):
        for l in self._logos:
            if l.get("url") == url:
                return l["id"]
        lid = self._id()
        self._logos.append({"id": lid, "name": name, "url": url})
        self.created_logos.append((name, url))
        return lid

    def create_channel(self, payload):
        ch = {**payload, "id": self._id()}
        self._channels.append(ch)
        return ch

    def update_channel(self, channel_id, payload):
        for c in self._channels:
            if c["id"] == channel_id:
                c.update(payload)
                return c
        raise KeyError(channel_id)

    def match_epg(self, channel_ids):
        pass


class TestDispatcharrStreamsSkipsDisabledAccounts(unittest.TestCase):
    """Real feedback (Discord): using Dispatcharr AS A PROVIDER pulled every
    stream from every M3U account it had ever ingested, including ones
    switched off (is_active=False) in Dispatcharr's own UI -- exactly the
    streams an operator does NOT want probed or matched into a wantlist.
    Distinct from "Import from Dispatcharr" in Curate, which reads
    Dispatcharr's existing CHANNELS and matches them against the run's own
    separately-configured provider pool -- this bug was specific to
    streams(), the raw-catalogue path used when Dispatcharr itself is
    configured as a probarr provider.
    """

    def _client(self, accounts, streams):
        from probarr.sources.dispatcharr import Dispatcharr
        client = Dispatcharr("http://fake", "u", "p")

        def fake_api(method, path, body=None):
            if path.startswith("/api/m3u/accounts/"):
                return {"results": accounts}
            if path.startswith("/api/channels/streams/"):
                return {"results": streams}
            raise AssertionError(f"unexpected call: {method} {path}")
        client.api = fake_api
        return client

    def test_streams_from_a_disabled_account_are_excluded(self):
        accounts = [{"id": 1, "is_active": True}, {"id": 2, "is_active": False}]
        streams = [{"id": 10, "name": "Active One", "url": "http://x/1",
                   "m3u_account": 1},
                  {"id": 11, "name": "Disabled One", "url": "http://x/2",
                   "m3u_account": 2}]
        client = self._client(accounts, streams)
        names = [s.name for s in client.streams()]
        self.assertEqual(names, ["Active One"])

    def test_a_custom_stream_with_no_m3u_account_is_kept(self):
        accounts = [{"id": 1, "is_active": False}]
        streams = [{"id": 10, "name": "Custom", "url": "http://x/1",
                   "m3u_account": None}]
        client = self._client(accounts, streams)
        names = [s.name for s in client.streams()]
        self.assertEqual(names, ["Custom"])


class TestDispatcharrLogoPush(unittest.TestCase):
    """The bug behind the user's own suspicion: a logo picked from
    anywhere OTHER than the M3U's own tvg-logo (a saved EPG source's icon,
    a tv-logo/tv-logos search result) was never actually reaching
    Dispatcharr, because Dispatcharr only auto-creates a Logo row for a URL
    it saw itself while ingesting an M3U -- logo_by_url.get(url) silently
    returned None for anything else, and a plain `if logo_id:` guard meant
    the channel payload just never carried a logo_id at all. No error,
    no plan diff, nothing -- exactly the kind of silent miss that's hard
    to notice without checking Dispatcharr itself.
    """

    def _channel(self, url="https://raw.githubusercontent.com/tv-logo/"
                            "tv-logos/main/countries/united-kingdom/"
                            "bbc-one-uk.png"):
        return {"number": 101, "name": "BBC One",
                "primary": {"stream_id": 1}, "fallback": None,
                "logo_url": url}

    def test_push_creates_a_missing_logo_row_and_links_it(self):
        from probarr.dispatcharr_export import push
        client = FakeDispatcharrClient()
        result = push(client, [self._channel()], default_group_name="probarr")
        self.assertEqual(result["created"], 1)
        self.assertEqual(len(client.created_logos), 1)
        self.assertEqual(client.created_logos[0][1],
                         "https://raw.githubusercontent.com/tv-logo/tv-logos/"
                         "main/countries/united-kingdom/bbc-one-uk.png")
        new_ch = client._channels[0]
        self.assertIsNotNone(new_ch.get("logo_id"))
        linked_logo = next(l for l in client._logos
                           if l["id"] == new_ch["logo_id"])
        self.assertEqual(linked_logo["url"], self._channel()["logo_url"])

    def test_push_does_not_recreate_a_logo_that_already_exists(self):
        from probarr.dispatcharr_export import push
        url = self._channel()["logo_url"]
        client = FakeDispatcharrClient(
            existing_logos=[{"id": 5, "name": "BBC One", "url": url}])
        push(client, [self._channel()], default_group_name="probarr")
        self.assertEqual(client.created_logos, [])
        self.assertEqual(client._channels[0]["logo_id"], 5)

    def test_plan_reports_a_pending_logo_change_for_an_unmatched_url_without_creating_it(self):
        from probarr.dispatcharr_export import plan
        url = self._channel()["logo_url"]
        existing_ch = {"id": 7, "channel_number": 101, "name": "BBC One",
                      "streams": [1], "channel_group_id": 9, "logo_id": None}
        client = FakeDispatcharrClient(
            existing_channels=[existing_ch],
            existing_groups=[{"id": 9, "name": "probarr"}])
        result = plan(client, [self._channel(url)], default_group_name="probarr")
        # The whole point of plan(): describe what push WOULD do without
        # doing it -- so nothing on the fake client's Logo table should
        # have moved.
        self.assertEqual(client._logos, [])
        action = next(a for a in result["actions"] if a["number"] == 101)
        self.assertEqual(action["kind"], "update")
        logo_change = next(c for c in action["changes"] if c["field"] == "logo")
        self.assertEqual(logo_change["to_name"], "(new logo)")

    def test_plan_reports_unchanged_when_the_logo_already_matches(self):
        from probarr.dispatcharr_export import plan
        url = self._channel()["logo_url"]
        existing_ch = {"id": 7, "channel_number": 101, "name": "BBC One",
                      "streams": [1], "channel_group_id": 9, "logo_id": 5}
        client = FakeDispatcharrClient(
            existing_channels=[existing_ch],
            existing_logos=[{"id": 5, "name": "BBC One", "url": url}],
            existing_groups=[{"id": 9, "name": "probarr"}])
        result = plan(client, [self._channel(url)], default_group_name="probarr")
        action = next(a for a in result["actions"] if a["number"] == 101)
        self.assertEqual(action["kind"], "unchanged")


class TestProviderRename(Temp):
    """providers.rename(): renaming a saved provider in place, keeping its
    spec/concurrency/last_group_name -- and the cascade in web.py that
    keeps every lineup and run pointing at the SAME provider under its new
    name, rather than orphaning them (see _rename_provider's docstring)."""

    def test_rename_keeps_spec_and_concurrency(self):
        from probarr import providers
        providers.save(self.root, "old-name", "http://example/x.m3u", concurrency=3)
        new = providers.rename(self.root, "old-name", "new-name")
        self.assertEqual(new, "new-name")
        self.assertIsNone(providers.get(self.root, "old-name"))
        p = providers.get(self.root, "new-name")
        self.assertIsNotNone(p)
        self.assertEqual(p["spec"], "http://example/x.m3u")
        self.assertEqual(p["concurrency"], 3)

    def test_rename_keeps_last_group_name(self):
        from probarr import providers
        providers.save(self.root, "old-name", "http://example/x.m3u")
        providers.set_last_group_name(self.root, "old-name", "my group")
        providers.rename(self.root, "old-name", "new-name")
        p = providers.get(self.root, "new-name")
        self.assertEqual(p["last_group_name"], "my group")

    def test_rename_rejects_a_name_already_in_use(self):
        from probarr import providers
        providers.save(self.root, "one", "http://example/1.m3u")
        providers.save(self.root, "two", "http://example/2.m3u")
        with self.assertRaises(ValueError):
            providers.rename(self.root, "one", "two")
        # Neither provider should have been touched by the failed attempt.
        self.assertIsNotNone(providers.get(self.root, "one"))
        self.assertIsNotNone(providers.get(self.root, "two"))

    def test_rename_rejects_an_unknown_provider(self):
        from probarr import providers
        with self.assertRaises(ValueError):
            providers.rename(self.root, "does-not-exist", "whatever")

    def test_stored_scheme_is_not_leaked_into_the_json_file(self):
        """list_all() computes `scheme` fresh on every read (it is never
        written to disk) -- rename() must not accidentally freeze a stale
        copy of it into providers.json when it re-saves the list."""
        from probarr import providers
        import json
        providers.save(self.root, "old-name", "http://example/x.m3u")
        providers.rename(self.root, "old-name", "new-name")
        with open(providers._path(self.root)) as f:
            raw = json.load(f)
        self.assertNotIn("scheme", raw[0])


class TestProviderAsSource(Temp):
    """as_source: whether a saved provider is offered as something a run
    can probe FROM (New Run / Browse / Lineups dropdowns), as opposed to a
    Dispatcharr connection kept purely as a push target."""

    def test_default_is_a_source_when_not_specified(self):
        from probarr import providers
        providers.save(self.root, "plain", "http://example/x.m3u")
        p = providers.get(self.root, "plain")
        self.assertNotIn("as_source", p)  # absent means "treat as True"

    def test_can_be_saved_as_false(self):
        from probarr import providers
        providers.save(self.root, "push-only", "dispatcharr://u:p@host:9191",
                        as_source=False)
        p = providers.get(self.root, "push-only")
        self.assertEqual(p["as_source"], False)

    def test_can_be_saved_as_true_explicitly(self):
        from probarr import providers
        providers.save(self.root, "d1", "dispatcharr://u:p@host:9191",
                        as_source=True)
        p = providers.get(self.root, "d1")
        self.assertEqual(p["as_source"], True)

    def test_re_saving_with_none_leaves_existing_value_untouched(self):
        from probarr import providers
        providers.save(self.root, "d1", "dispatcharr://u:p@host:9191",
                        as_source=False)
        providers.save(self.root, "d1", "dispatcharr://u:p@host:9191",
                        concurrency=2)
        p = providers.get(self.root, "d1")
        self.assertEqual(p["as_source"], False)
        self.assertEqual(p["concurrency"], 2)

    def test_api_list_exposes_as_source(self):
        import json
        from probarr import web as web_mod, providers
        providers.save(self.root, "push-only", "dispatcharr://u:p@host:9191",
                        as_source=False)
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        h.path = "/api/providers"
        sent = []
        h._send = lambda body, ctype="application/json", code=200: (
            sent.append((code, body)), sent)[-1]
        h.do_GET()
        code, body = sent[-1]
        d = json.loads(body)
        p = next(x for x in d["providers"] if x["name"] == "push-only")
        self.assertEqual(p["as_source"], False)


class TestPercentEncodedPathSegments(Temp):
    """A run id, provider name, or wantlist name typed with a space (or any
    other character encodeURIComponent() escapes) arrives here still
    percent-encoded -- do_GET/do_POST must decode it back before comparing
    against in-memory job keys or on-disk directory names, or every lookup
    for that id silently misses (see _do_GET's unquote)."""

    def _handler(self, path):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        h.path = path
        sent = []
        h._send = lambda body, ctype="application/json", code=200: (
            sent.append((code, body)), sent)[-1]
        return h, sent

    def test_progress_polling_finds_a_run_id_with_a_space_in_it(self):
        import json
        from probarr import runs as runs_mod
        run_id = "F1 only test"
        with runs_mod._LOCK:
            runs_mod._JOBS[run_id] = {"run_id": run_id, "log": [],
                                       "state": "running",
                                       "stop_requested": False, "error": None}
        h, sent = self._handler("/api/run/" + run_id.replace(" ", "%20") + "/progress")
        h.do_GET()
        code, body = sent[-1]
        d = json.loads(body)
        self.assertEqual(code, 200, body)
        self.assertEqual(d["state"], "running")
        self.assertNotEqual(d.get("error"), "unknown run")

    def test_progress_polling_falls_back_to_disk_for_a_run_id_with_a_space(self):
        import json
        from probarr.store import RunStore
        run_id = "F1 only test"
        RunStore(self.root, run_id, create=True).write_meta({"run_state": "done"})
        h, sent = self._handler("/api/run/" + run_id.replace(" ", "%20") + "/progress")
        h.do_GET()
        code, body = sent[-1]
        d = json.loads(body)
        self.assertEqual(code, 200, body)
        self.assertEqual(d["state"], "done")


class TestProviderRenameCascades(Temp):
    """The web.py endpoint: renaming must not orphan a lineup or run that
    already points at the provider by its old name."""

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: (
            sent.append((code, body)), sent)[-1]
        return h, sent

    def test_renaming_updates_a_lineup_that_used_the_old_name(self):
        import json
        from probarr import providers, lineups
        providers.save(self.root, "old-name", "http://example/x.m3u")
        lineups.save(self.root, "my-lineup", provider="old-name")
        h, sent = self._handler()
        h._rename_provider("old-name", {"new_name": "new-name"})
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        d = json.loads(body)
        self.assertEqual(d["relinked_lineups"], 1)
        lu = lineups.get(self.root, "my-lineup")
        self.assertEqual(lu["provider"], "new-name")

    def test_renaming_updates_a_runs_provider_name(self):
        import json
        from probarr import providers
        from probarr.store import RunStore
        providers.save(self.root, "old-name", "http://example/x.m3u")
        store = RunStore(self.root, "run1", create=True)
        store.write_meta({"provider_name": "old-name", "source": "http://example/x.m3u"})
        h, sent = self._handler()
        h._rename_provider("old-name", {"new_name": "new-name"})
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        d = json.loads(body)
        self.assertEqual(d["relinked_runs"], 1)
        meta = RunStore(self.root, "run1").read_meta()
        self.assertEqual(meta["provider_name"], "new-name")

    def test_a_lineup_or_run_on_a_different_provider_is_left_alone(self):
        import json
        from probarr import providers, lineups
        from probarr.store import RunStore
        providers.save(self.root, "old-name", "http://example/x.m3u")
        providers.save(self.root, "other", "http://example/y.m3u")
        lineups.save(self.root, "other-lineup", provider="other")
        store = RunStore(self.root, "run1", create=True)
        store.write_meta({"provider_name": "other"})
        h, sent = self._handler()
        h._rename_provider("old-name", {"new_name": "new-name"})
        d = json.loads(sent[-1][1])
        self.assertEqual(d["relinked_lineups"], 0)
        self.assertEqual(d["relinked_runs"], 0)
        self.assertEqual(lineups.get(self.root, "other-lineup")["provider"], "other")
        self.assertEqual(RunStore(self.root, "run1").read_meta()["provider_name"], "other")

    def test_rejects_a_collision_and_reports_the_error(self):
        import json
        from probarr import providers
        providers.save(self.root, "one", "http://example/1.m3u")
        providers.save(self.root, "two", "http://example/2.m3u")
        h, sent = self._handler()
        h._rename_provider("one", {"new_name": "two"})
        code, body = sent[-1]
        self.assertEqual(code, 400)
        self.assertIn("error", json.loads(body))


class TestClaimsRegistry(Temp):
    """claims.py: which Dispatcharr channel ids probarr already owns. Kept
    as its own tiny persistence module -- see claims.py's docstring for why
    this is checked before push() knows anything about numbers at all."""

    def test_claim_then_read_all_round_trips(self):
        from probarr import claims
        claims.claim(self.root, 42, "BBCONE", "BBC One", source="run:r1")
        all_claims = claims.read_all(self.root)
        self.assertIn(42, all_claims)
        self.assertEqual(all_claims[42]["key"], "BBCONE")
        self.assertEqual(all_claims[42]["name"], "BBC One")
        self.assertTrue(claims.is_claimed(self.root, 42))
        self.assertFalse(claims.is_claimed(self.root, 999))

    def test_claim_records_the_live_number_for_display(self):
        """The number is purely cosmetic (see claim()'s own docstring) --
        Curate shows it as "linked · Dispatcharr live channel N" because
        showing the internal dispatcharr_id there read as a second,
        conflicting channel number sitting right next to the real one."""
        from probarr import claims
        claims.claim(self.root, 42, "BBCONE", "BBC One", number=105)
        self.assertEqual(claims.read_all(self.root)[42]["number"], 105)
        self.assertEqual(claims.claimed_by_key(self.root)["BBCONE"]["number"], 105)

    def test_unclaim_removes_it(self):
        from probarr import claims
        claims.claim(self.root, 7, "X", "X")
        self.assertTrue(claims.unclaim(self.root, 7))
        self.assertFalse(claims.is_claimed(self.root, 7))
        self.assertFalse(claims.unclaim(self.root, 7),
                         "unclaiming something already gone should say so, not error")

    def test_claimed_by_key_is_the_reverse_index(self):
        from probarr import claims
        claims.claim(self.root, 42, "BBCONE", "BBC One", source="run:r1")
        by_key = claims.claimed_by_key(self.root)
        self.assertEqual(by_key["BBCONE"]["dispatcharr_id"], 42)
        self.assertEqual(by_key["BBCONE"]["name"], "BBC One")
        self.assertNotIn("ITV", by_key)


class TestChangedAlertOnlyFiresForTopTwoNegativeChanges(Temp):
    """Real usability complaint: the "Changed" chip/badge fired for ANY
    candidate's change, including a fallback stream ranked #5 that nobody
    was watching, and for improvements as much as regressions -- both are
    real information, but neither is what a curator logging in to check on
    their lineup actually needs interrupted for. Only a change that makes
    one of a channel's top-2 ranked candidates WORSE should surface here.
    """

    def _probe(self, key, sid, probed_at, w, h, status="ok", kbps=5000):
        return {"rec_key": f"{key}|{sid}", "channel_key": key, "stream_id": sid,
                "stream_name": sid, "status": status, "width": w, "height": h,
                "measured_kbps": kbps, "probed_at": probed_at}

    def _payload_for(self, store):
        from probarr.verify import annotate_placeholders
        by_channel = annotate_placeholders(store)
        return curate.build_payload(by_channel, store, False, None, None, None, None)

    def test_a_regression_on_the_top_ranked_candidate_is_reported(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw([{"key": "A", "number": 1, "name": "A"}], [])
        # s1 is clearly the best (1080p) -- rank #1.
        store.append(self._probe("A", "s1", 1000, 1920, 1080))
        store.append(self._probe("A", "s2", 1000, 720, 480))
        # Re-probe: s1 breaks.
        store.append(self._probe("A", "s1", 2000, 1920, 1080, status="dead"))
        store.append(self._probe("A", "s2", 2000, 720, 480))
        ch = next(c for c in self._payload_for(store)["channels"] if c["key"] == "A")
        self.assertTrue(any("stopped working" in m for m in ch["changes"]),
                        ch["changes"])

    def test_a_regression_buried_below_the_top_two_is_not_reported(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw([{"key": "A", "number": 1, "name": "A"}], [])
        # s1/s2 rank above s3 on resolution -- s3 is rank #3.
        store.append(self._probe("A", "s1", 1000, 1920, 1080))
        store.append(self._probe("A", "s2", 1000, 1280, 720))
        store.append(self._probe("A", "s3", 1000, 640, 480))
        store.append(self._probe("A", "s1", 2000, 1920, 1080))
        store.append(self._probe("A", "s2", 2000, 1280, 720))
        # Re-probe: only s3 (rank #3) breaks.
        store.append(self._probe("A", "s3", 2000, 640, 480, status="dead"))
        ch = next(c for c in self._payload_for(store)["channels"] if c["key"] == "A")
        self.assertEqual(ch["changes"], [],
                         "a regression on a candidate outside the top 2 must "
                         "not trigger a Changed alert")

    def test_an_improvement_on_the_top_ranked_candidate_is_not_reported(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw([{"key": "A", "number": 1, "name": "A"}], [])
        store.append(self._probe("A", "s1", 1000, 1280, 720))
        store.append(self._probe("A", "s2", 1000, 640, 480))
        # Re-probe: s1 gets BETTER (720p -> 1080p) -- real info, not urgent.
        store.append(self._probe("A", "s1", 2000, 1920, 1080))
        store.append(self._probe("A", "s2", 2000, 640, 480))
        ch = next(c for c in self._payload_for(store)["channels"] if c["key"] == "A")
        self.assertEqual(ch["changes"], [],
                         "an upgrade is not a negative change and must not "
                         "trigger a Changed alert")


class TestDispatcharrCurrentCandidateFlag(Temp):
    """Real bug found running the Wizard's "pull my Dispatcharr channels"
    path live: the "already in Dispatcharr" candidate badge was keyed off
    stream_id starting with "dispatcharr:<id>" -- which every candidate
    gets, not just the genuinely-already-assigned one, whenever Dispatcharr
    itself is the probing PROVIDER (exactly what that Wizard path sets up).
    build_payload() must instead carry the explicit is_dispatcharr_current
    flag _dispatcharr_import() stamps on its one real "this was already
    live" seed -- see web.py's seeds_for().
    """

    def test_only_the_explicitly_flagged_record_is_marked(self):
        from probarr.store import RunStore
        from probarr.verify import annotate_placeholders
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw([{"key": "A", "number": 1, "name": "A"}], [])
        store.append({"rec_key": "A|dispatcharr:1", "channel_key": "A",
                     "stream_id": "dispatcharr:1", "status": "ok",
                     "is_dispatcharr_current": True})
        store.append({"rec_key": "A|dispatcharr:2", "channel_key": "A",
                     "stream_id": "dispatcharr:2", "status": "ok"})
        by_channel = annotate_placeholders(store)
        payload = curate.build_payload(by_channel, store, False, None, None, None, None)
        ch = next(c for c in payload["channels"] if c["key"] == "A")
        flags = {c["stream_id"]: c["dispatcharr_current"] for c in ch["candidates"]}
        self.assertEqual(flags, {"dispatcharr:1": True, "dispatcharr:2": False})


class TestCurateShowsClaimStatus(Temp):
    """Real user request: seeing which channels are/aren't tagged in
    claims.py directly in Curate (not just inferred from a push preview),
    right next to the channel name, for debugging why a push would treat
    a channel as blocked/relink."""

    def test_build_payload_carries_the_claim_for_a_matched_channel(self):
        from probarr import claims
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw(
            [{"key": "BBCONE", "number": 101, "name": "BBC One"}], [])
        store.append({"rec_key": "BBCONE|s1", "channel_key": "BBCONE",
                     "stream_id": "s1", "status": "ok"})
        claims.claim(self.root, 42, "BBCONE", "BBC One")
        from probarr.verify import annotate_placeholders
        by_channel = annotate_placeholders(store)
        payload = curate.build_payload(by_channel, store, False, None, None, None,
                                       claims.claimed_by_key(self.root))
        ch = next(c for c in payload["channels"] if c["key"] == "BBCONE")
        self.assertEqual(ch["claim"]["dispatcharr_id"], 42)

    def test_build_payload_reports_none_for_an_unclaimed_channel(self):
        from probarr import claims
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw(
            [{"key": "BBCONE", "number": 101, "name": "BBC One"}], [])
        store.append({"rec_key": "BBCONE|s1", "channel_key": "BBCONE",
                     "stream_id": "s1", "status": "ok"})
        from probarr.verify import annotate_placeholders
        by_channel = annotate_placeholders(store)
        payload = curate.build_payload(by_channel, store, False, None, None, None,
                                       claims.claimed_by_key(self.root))
        ch = next(c for c in payload["channels"] if c["key"] == "BBCONE")
        self.assertIsNone(ch["claim"])


class TestDispatcharrPushRefusesUnclaimedNumberCollisions(unittest.TestCase):
    """Real user-reported worry: on an established Dispatcharr instance, a
    push previously matched purely by channel_number (see plan()/push()'s
    old `by_number` lookup) -- so pushing "BBC One" at number 101 would
    silently overwrite whatever ALREADY occupied number 101, even a
    completely unrelated hand-added channel. claimed_ids is the fix:
    a number match against an id claims.py has never seen is refused, not
    applied, unless it's a soft "relink" match with a resolution already on
    file (i.e. actually in claimed_ids).
    """

    def _channel(self, key="BBCONE", number=101, name="BBC One", stream_id=1):
        return {"key": key, "number": number, "name": name,
                "primary": {"stream_id": stream_id}, "fallback": None,
                "logo_url": ""}

    def test_plan_blocks_a_number_collision_with_no_name_or_stream_match(self):
        from probarr.dispatcharr_export import plan
        existing_ch = {"id": 7, "channel_number": 101, "name": "YoMamaTV",
                      "streams": [999], "channel_group_id": 9}
        client = FakeDispatcharrClient(existing_channels=[existing_ch],
                                      existing_groups=[{"id": 9, "name": "probarr"}])
        result = plan(client, [self._channel()], default_group_name="probarr",
                     claimed_ids=set())
        action = next(a for a in result["actions"] if a["number"] == 101)
        self.assertEqual(action["kind"], "blocked")
        self.assertEqual(action["dispatcharr_current"]["name"], "YoMamaTV")
        self.assertEqual(result["counts"]["blocked"], 1)

    def test_plan_offers_a_relink_when_the_name_matches(self):
        """The backup-restore case: Dispatcharr hands out a new id for a
        channel that is, to a human, obviously the same one as before.
        Matching name is enough to treat it as a soft conflict, not a
        scary unknown one."""
        from probarr.dispatcharr_export import plan
        existing_ch = {"id": 7, "channel_number": 101, "name": "BBC One",
                      "streams": [999], "channel_group_id": 9}
        client = FakeDispatcharrClient(existing_channels=[existing_ch],
                                      existing_groups=[{"id": 9, "name": "probarr"}])
        result = plan(client, [self._channel()], default_group_name="probarr",
                     claimed_ids=set())
        action = next(a for a in result["actions"] if a["number"] == 101)
        self.assertEqual(action["kind"], "relink")
        self.assertEqual(result["counts"]["relink"], 1)

    def test_plan_offers_a_relink_when_a_stream_already_overlaps(self):
        from probarr.dispatcharr_export import plan
        existing_ch = {"id": 7, "channel_number": 101, "name": "Some Old Name",
                      "streams": [1], "channel_group_id": 9}
        client = FakeDispatcharrClient(existing_channels=[existing_ch],
                                      existing_groups=[{"id": 9, "name": "probarr"}])
        result = plan(client, [self._channel(stream_id=1)],
                     default_group_name="probarr", claimed_ids=set())
        action = next(a for a in result["actions"] if a["number"] == 101)
        self.assertEqual(action["kind"], "relink")

    def test_plan_treats_a_claimed_id_as_an_ordinary_update(self):
        from probarr.dispatcharr_export import plan
        existing_ch = {"id": 7, "channel_number": 101, "name": "BBC One",
                      "streams": [1], "channel_group_id": 9}
        client = FakeDispatcharrClient(existing_channels=[existing_ch],
                                      existing_groups=[{"id": 9, "name": "probarr"}])
        result = plan(client, [self._channel()], default_group_name="probarr",
                     claimed_ids={7})
        action = next(a for a in result["actions"] if a["number"] == 101)
        self.assertEqual(action["kind"], "unchanged")

    def test_plan_with_claimed_ids_none_keeps_old_ungated_behaviour(self):
        """None is the default -- every caller that hasn't been taught
        about claims yet (or a test not passing it) must see exactly the
        pre-existing behaviour, not suddenly start blocking things."""
        from probarr.dispatcharr_export import plan
        existing_ch = {"id": 7, "channel_number": 101, "name": "YoMamaTV",
                      "streams": [999], "channel_group_id": 9}
        client = FakeDispatcharrClient(existing_channels=[existing_ch],
                                      existing_groups=[{"id": 9, "name": "probarr"}])
        result = plan(client, [self._channel()], default_group_name="probarr")
        action = next(a for a in result["actions"] if a["number"] == 101)
        self.assertEqual(action["kind"], "update")

    def test_push_refuses_to_touch_an_unclaimed_number_collision(self):
        from probarr.dispatcharr_export import push
        existing_ch = {"id": 7, "channel_number": 101, "name": "YoMamaTV",
                      "streams": [999], "channel_group_id": 9}
        client = FakeDispatcharrClient(existing_channels=[existing_ch],
                                      existing_groups=[{"id": 9, "name": "probarr"}])
        result = push(client, [self._channel()], default_group_name="probarr",
                     claimed_ids=set())
        self.assertEqual(result["updated"], 0,
                         "an unclaimed collision must never be updated")
        self.assertEqual(client._channels[0]["name"], "YoMamaTV",
                         "the unrelated channel's real data must be untouched")
        self.assertEqual(len(result["blocked"]), 1)
        self.assertEqual(result["blocked"][0]["dispatcharr_name"], "YoMamaTV")
        self.assertEqual(result["touched"], [])

    def test_push_updates_and_records_a_touch_once_claimed(self):
        from probarr.dispatcharr_export import push
        existing_ch = {"id": 7, "channel_number": 101, "name": "BBC One",
                      "streams": [999], "channel_group_id": 9}
        client = FakeDispatcharrClient(existing_channels=[existing_ch],
                                      existing_groups=[{"id": 9, "name": "probarr"}])
        result = push(client, [self._channel()], default_group_name="probarr",
                     claimed_ids={7})
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["blocked"], [])
        self.assertEqual(len(result["touched"]), 1)
        self.assertEqual(result["touched"][0],
                         {"key": "BBCONE", "id": 7, "name": "BBC One", "number": 101})

    def test_push_records_a_touch_for_a_brand_new_channel_it_creates(self):
        from probarr.dispatcharr_export import push
        client = FakeDispatcharrClient()
        result = push(client, [self._channel()], default_group_name="probarr",
                     claimed_ids=set())
        self.assertEqual(result["created"], 1)
        self.assertEqual(len(result["touched"]), 1)
        self.assertEqual(result["touched"][0]["key"], "BBCONE")


class TestStore(Temp):
    def _store(self):
        s = RunStore(self.root, "run1")
        s.write_wantlist_raw([{"number": 1, "name": "One", "key": "ONE"}], [])
        return s

    def test_newest_record_for_a_probe_wins(self):
        s = self._store()
        s.append({"rec_key": "ONE|a", "channel_key": "ONE", "status": "dead"})
        s.append({"rec_key": "ONE|a", "channel_key": "ONE", "status": "ok"})
        self.assertEqual([r["status"] for r in s.load()], ["ok"])
        self.assertEqual(len(s.load(dedupe=False)), 2)

    def test_drop_channel_clears_wantlist_and_results(self):
        s = self._store()
        s.append({"rec_key": "ONE|a", "channel_key": "ONE", "status": "ok"})
        self.assertEqual(s.drop_channel("ONE"), 1)
        self.assertEqual(s.load(), [])
        self.assertEqual(s.read_wantlist()["wanted"], [])

    def test_removals_are_staged_and_cleared(self):
        s = self._store()
        s.add_removal("ONE", 101, "One")
        self.assertEqual(s.read_removals()[0]["number"], 101)
        s.add_removal("ONE", 101, "One")          # idempotent, not duplicated
        self.assertEqual(len(s.read_removals()), 1)
        s.clear_removal("ONE")
        self.assertEqual(s.read_removals(), [])


class TestSearchProgrammesAt(unittest.TestCase):
    """Guide.search_programmes_at(): "which channel was actually showing
    X around this time" -- the opposite question from now_playing(), for
    identifying which channel a misassigned stream actually belongs to."""

    def _guide(self, entries):
        """entries: [(channel_id, display_name, title, start_dt, stop_dt_or_None)]"""
        from probarr.epg import Guide
        g = Guide()
        for cid, name, title, start, stop in entries:
            g.display_names.setdefault(cid, []).append(name)
            g.programmes.setdefault(cid, []).append((start, stop, title, ""))
        return g

    def test_finds_a_title_match_on_a_different_channel(self):
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        g = self._guide([
            ("c1", "Sky Cinema Action", "Green Lantern", now, now + datetime.timedelta(hours=2)),
            ("c2", "Sky Cinema Comedy", "Grease", now, now + datetime.timedelta(hours=2)),
        ])
        hits = g.search_programmes_at("Grease", now)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["guide_id"], "c2")
        self.assertEqual(hits[0]["guide_name"], "Sky Cinema Comedy")

    def test_ignores_a_match_outside_the_tolerance_window(self):
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        g = self._guide([
            ("c2", "Sky Cinema Comedy", "Grease",
             now + datetime.timedelta(hours=6), now + datetime.timedelta(hours=8)),
        ])
        self.assertEqual(g.search_programmes_at("Grease", now, tolerance_minutes=90), [])

    def test_case_insensitive_substring_match(self):
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        g = self._guide([("c2", "Sky Cinema Comedy", "GREASE (1978)", now, now)])
        hits = g.search_programmes_at("grease", now)
        self.assertEqual(len(hits), 1)

    def test_a_programme_with_no_stop_is_treated_as_a_few_hours_long(self):
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        g = self._guide([("c2", "Sky Cinema Comedy", "Grease",
                          now - datetime.timedelta(minutes=30), None)])
        hits = g.search_programmes_at("Grease", now)
        self.assertEqual(len(hits), 1)


class TestMoveCandidate(Temp):
    """store.move_candidate(): re-key one candidate onto a different
    channel, keeping its probe results and images -- for a stream a human
    has recognised as belonging elsewhere (wrong provider playlist entry)."""

    def test_moves_the_record_to_the_new_channel(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_meta({})
        store.append({"rec_key": "SKYCINEMAACTION|s1", "channel_key": "SKYCINEMAACTION",
                     "stream_id": "s1", "stream_name": "Sky Cinema Action",
                     "status": "ok"})
        new_rk = store.move_candidate("SKYCINEMAACTION|s1", "SKYCINEMADRAMA")
        self.assertEqual(new_rk, "SKYCINEMADRAMA|s1")
        rows = store.load()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["channel_key"], "SKYCINEMADRAMA")
        self.assertEqual(rows[0]["rec_key"], "SKYCINEMADRAMA|s1")
        # Left behind under its old identity entirely -- not still visible
        # to the old channel too.
        self.assertEqual([r for r in rows if r.get("channel_key") == "SKYCINEMAACTION"], [])

    def test_moves_the_captured_frame_file_too(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_meta({})
        store.append({"rec_key": "SKYCINEMAACTION|s1", "channel_key": "SKYCINEMAACTION",
                     "stream_id": "s1", "status": "ok", "frame": "frames/x.jpg"})
        old_frame = store.frame_path("SKYCINEMAACTION|s1")
        os.makedirs(os.path.dirname(old_frame), exist_ok=True)
        with open(old_frame, "wb") as f:
            f.write(b"a real frame")
        store.move_candidate("SKYCINEMAACTION|s1", "SKYCINEMADRAMA")
        new_frame = store.frame_path("SKYCINEMADRAMA|s1")
        self.assertFalse(os.path.exists(old_frame))
        self.assertTrue(os.path.exists(new_frame))
        rows = store.load()
        self.assertEqual(rows[0]["frame"],
                         "frames/" + RunStore.safe_name("SKYCINEMADRAMA|s1") + ".jpg")

    def test_clears_a_selection_that_pointed_at_the_old_rec_key(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_meta({})
        store.append({"rec_key": "SKYCINEMAACTION|s1", "channel_key": "SKYCINEMAACTION",
                     "stream_id": "s1", "status": "ok"})
        store.write_selection({"SKYCINEMAACTION": {"primary": "SKYCINEMAACTION|s1",
                                                    "streams": ["SKYCINEMAACTION|s1"]}})
        store.move_candidate("SKYCINEMAACTION|s1", "SKYCINEMADRAMA")
        sel = store.read_selection()
        self.assertNotIn("primary", sel["SKYCINEMAACTION"])
        self.assertEqual(sel["SKYCINEMAACTION"]["streams"], [])

    def test_unknown_rec_key_returns_none(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_meta({})
        self.assertIsNone(store.move_candidate("NOPE|s1", "ELSEWHERE"))


class TestCandidateMoveEndpoint(Temp):

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: (
            sent.append((code, body)), sent)[-1]
        return h, sent

    def test_move_via_endpoint(self):
        import json, io
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_meta({})
        store.append({"rec_key": "SKYCINEMAACTION|s1", "channel_key": "SKYCINEMAACTION",
                     "stream_id": "s1", "status": "ok"})
        h, sent = self._handler()
        h.path = "/api/run/run1/candidate-move"
        h.command = "POST"
        h.headers = {"Host": "127.0.0.1", "Referer": "http://127.0.0.1/run/run1/curate"}
        payload = json.dumps({"rec_key": "SKYCINEMAACTION|s1",
                             "channel_key": "SKYCINEMADRAMA"}).encode()
        h.headers["Content-Length"] = str(len(payload))
        h.rfile = io.BytesIO(payload)
        h._do_POST()
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        d = json.loads(body)
        self.assertEqual(d["rec_key"], "SKYCINEMADRAMA|s1")

    def test_unknown_candidate_is_a_404(self):
        import json, io
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_meta({})
        h, sent = self._handler()
        h.path = "/api/run/run1/candidate-move"
        h.command = "POST"
        h.headers = {"Host": "127.0.0.1", "Referer": "http://127.0.0.1/run/run1/curate"}
        payload = json.dumps({"rec_key": "NOPE|s1", "channel_key": "ELSEWHERE"}).encode()
        h.headers["Content-Length"] = str(len(payload))
        h.rfile = io.BytesIO(payload)
        h._do_POST()
        code, body = sent[-1]
        self.assertEqual(code, 404, body)


class TestEpgProgrammeSearchEndpoint(Temp):
    """/api/run/<id>/epg-programme-search backs Delete stream's "search the
    guide first" escape hatch -- before removing a stream that's plainly
    wrong for its channel, this answers whether it might belong elsewhere."""

    def _guide(self, name, entries):
        import datetime
        xml = os.path.join(self.root, name + ".xml")
        body = "".join(
            f'<channel id="{cid}"><display-name>{cname}</display-name></channel>'
            f'<programme channel="{cid}" start="{start.strftime("%Y%m%d%H%M%S +0000")}" '
            f'stop="{stop.strftime("%Y%m%d%H%M%S +0000")}">'
            f'<title>{title}</title></programme>'
            for cid, cname, title, start, stop in entries)
        with open(xml, "w", encoding="utf-8") as f:
            f.write(f'<?xml version="1.0"?><tv>{body}</tv>')
        from probarr import epgsources
        epgsources.save(self.root, name, pathlib.Path(xml).as_uri())

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: (
            sent.append((code, body)), sent)[-1]
        return h, sent

    def test_finds_the_right_channel_from_the_candidates_own_probe_time(self):
        import json, datetime, time
        from probarr.store import RunStore
        # Relative to "now", not a fixed timestamp -- the guide loader's
        # own retention window is centred on real "now" at load time, not
        # on this candidate's probed_at, so a hardcoded absolute value
        # eventually falls outside that window as real time passes and
        # starts failing this test through no fault of the code under test.
        probed_at = time.time() - 3600
        at = datetime.datetime.fromtimestamp(probed_at, datetime.timezone.utc)
        self._guide("sky-guide", [
            ("c1", "Sky Cinema Action", "Green Lantern",
             at - datetime.timedelta(minutes=10), at + datetime.timedelta(hours=1)),
            ("c2", "Sky Cinema Comedy", "Grease",
             at - datetime.timedelta(minutes=10), at + datetime.timedelta(hours=1)),
        ])
        store = RunStore(self.root, "run1", create=True)
        store.write_meta({})
        store.append({"rec_key": "SKYCINEMAACTION|s1", "channel_key": "SKYCINEMAACTION",
                     "stream_id": "s1", "stream_name": "Sky Cinema Action",
                     "status": "ok", "probed_at": probed_at})
        h, sent = self._handler()
        h._epg_programme_search("run1", "SKYCINEMAACTION|s1", "Grease")
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        d = json.loads(body)
        self.assertEqual(len(d["hits"]), 1)
        self.assertEqual(d["hits"][0]["guide_name"], "Sky Cinema Comedy")

    def test_unknown_candidate_is_a_404(self):
        import json
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_meta({})
        store.append({"rec_key": "BBCONE|s1", "channel_key": "BBCONE",
                     "stream_id": "s1", "status": "ok", "probed_at": 1787905151.0})
        h, sent = self._handler()
        h._epg_programme_search("run1", "NOPE|s1", "Grease")
        code, body = sent[-1]
        self.assertEqual(code, 404, body)

    def test_blank_query_returns_no_hits_without_erroring(self):
        import json
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_meta({})
        store.append({"rec_key": "BBCONE|s1", "channel_key": "BBCONE",
                     "stream_id": "s1", "status": "ok", "probed_at": 1787905151.0})
        h, sent = self._handler()
        h._epg_programme_search("run1", "BBCONE|s1", "")
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        self.assertEqual(json.loads(body)["hits"], [])


class TestEpgList(Temp):
    def _guide(self, channels):
        xml = os.path.join(self.root, "guide.xml")
        body = "".join(f'<channel id="{cid}"><display-name>{name}</display-name></channel>'
                       for cid, name in channels)
        with open(xml, "w", encoding="utf-8") as f:
            f.write(f'<?xml version="1.0"?><tv>{body}</tv>')
        from probarr import epgsources
        # KNM fix (probarr-9wl): pathlib.as_uri(), not string concat --
        # "file://" + xml is malformed on Windows (file://B:\...) and
        # fails in urlopen; as_uri() produces a real file:///B:/... URL.
        epgsources.save(self.root, "test-guide", pathlib.Path(xml).as_uri())

    def test_collapses_sd_hd_pairs_to_one_row(self):
        from probarr import epgcheck
        self._guide([("1", "BBC One"), ("2", "BBC One HD")])
        out = epgcheck.list_channels(self.root, "test-guide", Normalizer())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["guide_name"], "BBC One")

    def test_groups_real_regional_variants_under_one_row_with_alts(self):
        from probarr import epgcheck
        self._guide([("1", "BBC One London"), ("2", "BBC One North West"),
                     ("3", "BBC One Scotland")])
        out = epgcheck.list_channels(self.root, "test-guide", Normalizer())
        # Nothing is discarded -- one row for the whole family, every
        # region (including the representative itself) still reachable:
        # the representative plus two alts covers all three variants.
        self.assertEqual(len(out), 1)
        row = out[0]
        self.assertIn("alts", row)
        self.assertEqual(len(row["alts"]) + 1, 3)

    def test_strips_a_glued_country_code_from_the_display_name(self):
        # Real data seen from open-epg.com's UK feed: <display-name> is
        # literally "4Seven.uk", not a real display name -- shown verbatim
        # and written into a wantlist as-is otherwise ("4Seven.uk | 4Seven.uk").
        from probarr import epgcheck
        self._guide([("1", "4Seven.uk"), ("2", "5Star.uk")])
        out = epgcheck.list_channels(self.root, "test-guide", Normalizer())
        names = sorted(c["guide_name"] for c in out)
        self.assertEqual(names, ["4Seven", "5Star"])


class TestEpgCacheStampede(Temp):
    """KNM fix (probarr-vz7): concurrent callers for the same EPG source URL
    used to each independently re-download/re-parse the guide -- confirmed
    live via py-spy as six threads simultaneously inside ElementTree
    parsing, pegging the container at 100%+ CPU. load_cached() and
    _indexed_guide() now serialize per-url so only the first caller does the
    real work and the rest reuse it. These tests prove that directly: spin
    up N concurrent callers for the same url and assert the expensive work
    (Guide.load) ran once, not N times.
    """

    def _guide_xml(self):
        # A plain filesystem path, not a file:// URL -- Guide.load/_open
        # accepts either, and file:// URLs don't round-trip through
        # url2pathname on Windows (a separate, pre-existing, unrelated bug).
        xml = os.path.join(self.root, "guide.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0"?><tv>'
                    '<channel id="c1"><display-name>BBC One</display-name></channel>'
                    '</tv>')
        return xml

    def test_concurrent_load_cached_calls_parse_the_guide_only_once(self):
        import threading
        from probarr import epgcheck

        epgcheck._cache.clear()
        epgcheck._locks.clear()
        url = self._guide_xml()

        real_load = epgcheck.Guide.load
        call_count = []
        start_gate = threading.Event()

        def slow_load(*args, **kwargs):
            # Force real overlap: every thread reaches this before any of
            # them returns, so a missing lock would show up as call_count > 1.
            call_count.append(1)
            start_gate.wait(timeout=5)
            return real_load(*args, **kwargs)

        results = []
        errors = []

        def worker():
            try:
                results.append(epgcheck.load_cached(url, root=None))
            except Exception as e:
                errors.append(e)

        with unittest.mock.patch.object(epgcheck.Guide, "load", side_effect=slow_load):
            threads = [threading.Thread(target=worker) for _ in range(6)]
            for t in threads:
                t.start()
            # Give every thread a chance to reach the lock before releasing
            # the first one through the parse -- proves they actually
            # serialized rather than just happening to run in order.
            import time as _time
            _time.sleep(0.2)
            start_gate.set()
            for t in threads:
                t.join(timeout=5)

        self.assertEqual(len(errors), 0, errors)
        self.assertEqual(len(results), 6)
        self.assertEqual(call_count, [1],
                          "Guide.load should run exactly once for 6 concurrent "
                          "callers of the same url -- the rest must reuse the "
                          "cached result instead of each re-parsing")
        # All 6 threads got back the same Guide instance from the cache.
        self.assertTrue(all(g is results[0] for g in results))

    def test_concurrent_indexed_guide_calls_build_the_index_only_once(self):
        import threading
        from probarr import epgcheck
        from probarr.normalize import Normalizer

        epgcheck._cache.clear()
        epgcheck._locks.clear()
        epgcheck._indexed.clear()
        url = self._guide_xml()
        normalizer = Normalizer()

        real_build = epgcheck.Guide.build_name_index
        call_count = []
        start_gate = threading.Event()

        def slow_build(self_guide, *args, **kwargs):
            call_count.append(1)
            start_gate.wait(timeout=5)
            return real_build(self_guide, *args, **kwargs)

        results = []
        errors = []

        def worker():
            try:
                results.append(epgcheck._indexed_guide(url, normalizer, None))
            except Exception as e:
                errors.append(e)

        with unittest.mock.patch.object(epgcheck.Guide, "build_name_index", slow_build):
            threads = [threading.Thread(target=worker) for _ in range(6)]
            for t in threads:
                t.start()
            import time as _time
            _time.sleep(0.2)
            start_gate.set()
            for t in threads:
                t.join(timeout=5)

        self.assertEqual(len(errors), 0, errors)
        self.assertEqual(len(results), 6)
        self.assertEqual(call_count, [1],
                          "build_name_index should run exactly once for 6 "
                          "concurrent callers of the same url")


class TestExpectedNowHonoursExplicitEpgSource(Temp):
    """Real bug report: after explicitly picking a different EPG source for
    a channel in Check EPG, diagnosing that channel still captured the OLD
    source's programme as `expected`. Root cause -- _expected_now() only
    ever walked every saved source in list order and took whichever matched
    first, blind to the channel's own selection.json pick. Everywhere else
    an explicit epg_source is honoured (the live Check EPG panel, the
    actual Dispatcharr push via _resolve_epg_overrides()); this is the one
    place that silently wasn't.
    """

    def _guide(self, name, channel_name, programme_title):
        import datetime
        xml = os.path.join(self.root, name + ".xml")
        now = datetime.datetime.now(datetime.timezone.utc)
        start = (now - datetime.timedelta(minutes=30)).strftime("%Y%m%d%H%M%S +0000")
        stop = (now + datetime.timedelta(minutes=30)).strftime("%Y%m%d%H%M%S +0000")
        body = (f'<channel id="c1"><display-name>{channel_name}</display-name></channel>'
               f'<programme channel="c1" start="{start}" stop="{stop}">'
               f'<title>{programme_title}</title></programme>')
        with open(xml, "w", encoding="utf-8") as f:
            f.write(f'<?xml version="1.0"?><tv>{body}</tv>')
        from probarr import epgsources
        # KNM fix (probarr-9wl): pathlib.as_uri(), not string concat --
        # "file://" + xml is malformed on Windows (file://B:\...) and
        # fails in urlopen; as_uri() produces a real file:///B:/... URL.
        epgsources.save(self.root, name, pathlib.Path(xml).as_uri())

    def _record(self):
        return {"channel_key": "NATGEO", "stream_name": "National Geographic",
                "tvg_id": ""}

    def test_falls_back_to_the_first_saved_source_with_no_explicit_pick(self):
        from probarr import web as web_mod
        from probarr.store import RunStore
        web_mod.Handler.root = self.root
        self._guide("aaa-old", "National Geographic", "Old Programme")
        self._guide("zzz-new", "National Geographic", "New Programme")
        store = RunStore(self.root, "run1")
        got = web_mod.Handler._expected_now(self._record(), store)
        self.assertEqual(got["title"], "Old Programme")

    def test_an_explicitly_picked_source_wins_even_when_listed_second(self):
        from probarr import web as web_mod
        from probarr.store import RunStore
        web_mod.Handler.root = self.root
        self._guide("aaa-old", "National Geographic", "Old Programme")
        self._guide("zzz-new", "National Geographic", "New Programme")
        store = RunStore(self.root, "run1")
        store.write_selection({"NATGEO": {"epg_source": "zzz-new"}})
        got = web_mod.Handler._expected_now(self._record(), store)
        self.assertEqual(got["title"], "New Programme")

    def test_falls_back_when_the_picked_source_does_not_match_this_channel(self):
        from probarr import web as web_mod
        from probarr.store import RunStore
        web_mod.Handler.root = self.root
        self._guide("aaa-old", "National Geographic", "Old Programme")
        self._guide("zzz-new", "Some Other Channel", "New Programme")
        store = RunStore(self.root, "run1")
        store.write_selection({"NATGEO": {"epg_source": "zzz-new"}})
        got = web_mod.Handler._expected_now(self._record(), store)
        self.assertEqual(got["title"], "Old Programme")


class TestWatermarkCrop(Temp):
    """A channel nobody has marked a watermark area for must trigger NO
    work at all, not even a fast local one -- the whole point raised when
    this was scoped. _watermark_crop() is the only place cropping ever
    happens, so its 404-with-no-box behaviour IS the entire enforcement.
    """

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="text/plain", code=200: sent.append(
            (code, ctype, body))
        h._file = lambda run_id, rest: sent.append(("FILE", rest)) or sent
        return h, sent

    def test_no_watermark_box_is_a_404_and_never_touches_the_frame(self):
        from probarr.store import RunStore
        import unittest.mock
        store = RunStore(self.root, "run1")
        store.write_selection({"BBCONE": {"group": "News"}})  # no watermark_box
        h, sent = self._handler()
        with unittest.mock.patch("probarr.web.subprocess") as fake_subprocess:
            h._watermark_crop("run1", "BBCONE|s1")
            fake_subprocess.run.assert_not_called()
        self.assertEqual(sent[0][0], 404)

    def test_a_box_marked_on_an_earlier_run_of_the_same_lineup_still_crops(self):
        """Real reported bug: Curate's own page correctly shows "Redraw
        watermark area" for a channel whose box lives only on the lineup
        (inherited, same as EPG source/group/name) -- but this endpoint used
        to read ONLY the run's own selection.json, so the crop 404'd on
        every fresh run of an existing lineup regardless of what the button
        said."""
        from probarr.store import RunStore
        from probarr import lineups as lineups_mod
        import unittest.mock
        lineups_mod.save(self.root, "my-lineup")
        lineups_mod.set_preference(self.root, "my-lineup", "BBCONE",
                                   watermark_box={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1})
        store = RunStore(self.root, "run1")
        store.write_meta({"lineup": "my-lineup"})
        store.write_selection({})  # nothing saved in THIS run
        frame_path = store.frame_path("BBCONE|s1")
        os.makedirs(os.path.dirname(frame_path), exist_ok=True)
        with open(frame_path, "wb") as f:
            f.write(b"not a real jpeg, ffmpeg is mocked")
        h, sent = self._handler()
        with unittest.mock.patch("probarr.web.subprocess") as fake_subprocess:
            fake_subprocess.CalledProcessError = Exception
            fake_subprocess.TimeoutExpired = Exception

            def fake_run(cmd, **kw):
                with open(cmd[-1], "wb") as f:
                    f.write(b"cropped")
            fake_subprocess.run.side_effect = fake_run
            h._watermark_crop("run1", "BBCONE|s1")
        self.assertEqual(sent[0][0], "FILE")

    def test_this_runs_own_box_wins_over_an_inherited_one(self):
        from probarr.store import RunStore
        from probarr import lineups as lineups_mod
        import unittest.mock
        lineups_mod.save(self.root, "my-lineup")
        lineups_mod.set_preference(self.root, "my-lineup", "BBCONE",
                                   watermark_box={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1})
        store = RunStore(self.root, "run1")
        store.write_meta({"lineup": "my-lineup"})
        store.write_selection({"BBCONE": {"watermark_box":
                               {"x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1}}})
        frame_path = store.frame_path("BBCONE|s1")
        os.makedirs(os.path.dirname(frame_path), exist_ok=True)
        with open(frame_path, "wb") as f:
            f.write(b"not a real jpeg, ffmpeg is mocked")
        h, sent = self._handler()
        with unittest.mock.patch("probarr.web.subprocess") as fake_subprocess:
            fake_subprocess.CalledProcessError = Exception
            fake_subprocess.TimeoutExpired = Exception
            captured_cmd = []

            def fake_run(cmd, **kw):
                captured_cmd.append(cmd)
                with open(cmd[-1], "wb") as f:
                    f.write(b"cropped")
            fake_subprocess.run.side_effect = fake_run
            h._watermark_crop("run1", "BBCONE|s1")
        self.assertEqual(sent[0][0], "FILE")
        # The run's own box (0.5/0.5) hashes differently from the inherited
        # one (0.1/0.1) -- the output filename baking in that hash is the
        # cheapest way to confirm which box coordinates actually got used.
        import hashlib
        own_hash = hashlib.sha256(
            b"0.5000:0.5000:0.1000:0.1000").hexdigest()[:10]
        self.assertIn(own_hash, sent[0][1][1])

    def test_missing_frame_file_is_a_404(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1")
        store.write_selection({"BBCONE": {"watermark_box":
                               {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1}}})
        h, sent = self._handler()
        # frame_path exists on disk for no candidate here -- 404, not a crash.
        h._watermark_crop("run1", "BBCONE|s1")
        self.assertEqual(sent[0][0], 404)

    def test_crops_the_existing_frame_and_serves_the_result(self):
        from probarr.store import RunStore
        import unittest.mock
        store = RunStore(self.root, "run1")
        store.write_selection({"BBCONE": {"watermark_box":
                               {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1}}})
        frame_path = store.frame_path("BBCONE|s1")
        os.makedirs(os.path.dirname(frame_path), exist_ok=True)
        with open(frame_path, "wb") as f:
            f.write(b"not a real jpeg, ffmpeg is mocked")
        h, sent = self._handler()
        with unittest.mock.patch("probarr.web.subprocess") as fake_subprocess:
            fake_subprocess.CalledProcessError = Exception
            fake_subprocess.TimeoutExpired = Exception

            def fake_run(cmd, **kw):
                # Simulate ffmpeg actually writing the output file.
                out_path = cmd[-1]
                with open(out_path, "wb") as f:
                    f.write(b"cropped")
            fake_subprocess.run.side_effect = fake_run
            h._watermark_crop("run1", "BBCONE|s1")
            fake_subprocess.run.assert_called_once()
        self.assertEqual(sent[0][0], "FILE")
        self.assertEqual(sent[0][1][0], "watermarks")
        self.assertTrue(sent[0][1][1].startswith(
            RunStore.safe_name("BBCONE|s1")))

    def test_redrawing_the_box_produces_a_different_cached_filename(self):
        from probarr.store import RunStore
        import unittest.mock
        store = RunStore(self.root, "run1")
        frame_path = store.frame_path("BBCONE|s1")
        os.makedirs(os.path.dirname(frame_path), exist_ok=True)
        with open(frame_path, "wb") as f:
            f.write(b"x")

        def crop_with(box):
            store.write_selection({"BBCONE": {"watermark_box": box}})
            h, sent = self._handler()
            with unittest.mock.patch("probarr.web.subprocess") as fake_subprocess:
                fake_subprocess.CalledProcessError = Exception
                fake_subprocess.TimeoutExpired = Exception
                def fake_run(cmd, **kw):
                    with open(cmd[-1], "wb") as f:
                        f.write(b"x")
                fake_subprocess.run.side_effect = fake_run
                h._watermark_crop("run1", "BBCONE|s1")
            return sent[0][1][1]

        name_a = crop_with({"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1})
        name_b = crop_with({"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.1})
        self.assertNotEqual(name_a, name_b)

    def test_a_re_probed_frame_invalidates_the_cached_crop_even_with_the_same_box(self):
        # Real bug, caught live: a candidate re-probed after its watermark
        # crop was already cached kept serving the OLD crop indefinitely --
        # "the file already exists" was the only check, so a completely
        # different picture underneath the same unchanged box never got
        # noticed. The box's own hash only invalidates when the MARKED
        # AREA changes; a re-probe changes the PICTURE, not the area.
        import time
        import unittest.mock
        from probarr.store import RunStore

        store = RunStore(self.root, "run1")
        store.write_selection({"BBCONE": {"watermark_box":
                               {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1}}})
        frame_path = store.frame_path("BBCONE|s1")
        os.makedirs(os.path.dirname(frame_path), exist_ok=True)

        def do_crop(marker):
            with open(frame_path, "wb") as f:
                f.write(marker)
            h, sent = self._handler()
            with unittest.mock.patch("probarr.web.subprocess") as fake_subprocess:
                fake_subprocess.CalledProcessError = Exception
                fake_subprocess.TimeoutExpired = Exception
                def fake_run(cmd, **kw):
                    # A real crop's bytes are derived from the source frame;
                    # standing in for that here with the same marker so the
                    # test can tell "regenerated from the new frame" apart
                    # from "served the stale cached file" by content, not
                    # just by whether ffmpeg was invoked.
                    with open(cmd[-1], "wb") as f:
                        f.write(marker)
                fake_subprocess.run.side_effect = fake_run
                h._watermark_crop("run1", "BBCONE|s1")
            out_name = sent[0][1][1]
            with open(os.path.join(store.dir, "watermarks", out_name), "rb") as f:
                return f.read()

        first = do_crop(b"original broadcast frame")
        self.assertEqual(first, b"original broadcast frame")

        # The frame file's mtime must genuinely be newer than the cached
        # crop's for this to be a fair test of the staleness check, not an
        # accident of both happening within the same filesystem-timestamp
        # tick.
        time.sleep(1.05)
        second = do_crop(b"re-probed, totally different content")
        self.assertEqual(second, b"re-probed, totally different content")


class TestEpgSourceConsensus(Temp):
    """probarr never scored EPG matches against each other or read a
    guide's own <icon> at all -- both real gaps, not different approaches
    to something already covered. Word-overlap scoring lets a household
    running more than one EPG source prefer whichever source's own name
    for a channel actually agrees with what it's called, and the icon
    becomes a real (if last-resort) source of a channel's logo.
    """

    def _guide(self, name, channels):
        xml = os.path.join(self.root, f"{name}.xml")
        body = "".join(
            f'<channel id="{cid}">'
            f'<display-name>{dname}</display-name>'
            + (f'<icon src="{icon}"/>' if icon else "") + '</channel>'
            for cid, dname, icon in channels)
        with open(xml, "w", encoding="utf-8") as f:
            f.write(f'<?xml version="1.0"?><tv>{body}</tv>')
        from probarr import epgsources
        # KNM fix (probarr-9wl): pathlib.as_uri(), not string concat --
        # "file://" + xml is malformed on Windows (file://B:\...) and
        # fails in urlopen; as_uri() produces a real file:///B:/... URL.
        epgsources.save(self.root, name, pathlib.Path(xml).as_uri())

    def test_word_set_ignores_punctuation_and_case(self):
        from probarr.epgcheck import _word_set
        self.assertEqual(_word_set("UK: BBC Two!"), {"UK", "BBC", "TWO"})

    def test_check_all_scores_by_shared_words_not_just_match_or_not(self):
        from probarr import epgcheck
        self._guide("good-guide", [("1", "BBC Two Lon", None)])
        self._guide("vague-guide", [("2", "BBC Two Lon", None)])
        out = epgcheck.check_all(self.root, "UK: BBC Two", "", Normalizer())
        # Both matched the identical entry (same fixture content) -- the
        # point here is that a real score is attached at all, not zero
        # regardless of how well the names actually agree.
        for entry in out:
            self.assertTrue(entry["matched"])
            self.assertGreaterEqual(entry["score"], 2)   # "BBC" and "TWO"

    def test_consensus_requires_at_least_two_sources_to_actually_agree(self):
        from probarr import epgcheck
        # One source matches well, the other doesn't carry this channel at
        # all -- a single opinion, however good, is not a consensus.
        self._guide("has-it", [("1", "BBC Two Lon", None)])
        self._guide("lacks-it", [("2", "Totally Different Channel", None)])
        out = epgcheck.check_all(self.root, "UK: BBC Two", "", Normalizer())
        winner = epgcheck.consensus_winner(out)
        self.assertIsNotNone(winner)
        self.assertEqual(winner["source"], "has-it")
        self.assertFalse(winner["consensus"])

    def test_consensus_true_when_two_sources_independently_agree(self):
        from probarr import epgcheck
        self._guide("src-a", [("1", "BBC Two Lon", None)])
        self._guide("src-b", [("2", "BBC Two North", None)])
        out = epgcheck.check_all(self.root, "UK: BBC Two", "", Normalizer())
        winner = epgcheck.consensus_winner(out)
        self.assertTrue(winner["consensus"])

    def test_logo_is_read_from_the_winning_sources_icon(self):
        from probarr import epgcheck
        self._guide("with-icon", [("1", "BBC Two Lon", "https://x/bbctwo.png")])
        out = epgcheck.check_all(self.root, "UK: BBC Two", "", Normalizer())
        winner = epgcheck.consensus_winner(out)
        self.assertEqual(winner["logo"], "https://x/bbctwo.png")

    def test_trust_tiebreaks_equally_scored_sources(self):
        from probarr import epgcheck
        # Two sources score identically for this channel -- give one of
        # them a real track record of winning past consensus checks and
        # confirm it's preferred over the other, not just whichever comes
        # first alphabetically.
        self._guide("aaa-newcomer", [("1", "BBC Two Lon", None)])
        self._guide("zzz-veteran", [("2", "BBC Two Lon", None)])
        epgcheck._bump_trust(self.root, "zzz-veteran", ["aaa-newcomer", "zzz-veteran"])
        for _ in range(9):
            epgcheck._bump_trust(self.root, "zzz-veteran", ["zzz-veteran"])
        out = epgcheck.check_all(self.root, "UK: BBC Two", "", Normalizer())
        winner = epgcheck.consensus_winner(out, root=self.root)
        self.assertEqual(winner["source"], "zzz-veteran")

    def test_bump_trust_is_best_effort_and_never_raises(self):
        from probarr import epgcheck
        # A root that cannot be written to (nonexistent parent) must not
        # bring down whatever real request triggered this as a side effect.
        epgcheck._bump_trust("/no/such/directory", "x", ["x"])  # must not raise

    def test_epg_fallback_logo_only_used_when_the_m3u_gave_none(self):
        # web.py's _resolve_curated(): the M3U's own tvg-logo always wins
        # when present -- _epg_fallback_logo() is only ever CALLED for a
        # channel whose primary candidate's logo is falsy in the first
        # place, so this exercises the fallback resolver itself.
        from probarr import web as web_mod
        self._guide("only-guide", [("1", "BBC Two Lon", "https://x/bbctwo.png")])
        web_mod.Handler.root = self.root
        handler = web_mod.Handler.__new__(web_mod.Handler)
        self.assertEqual(
            handler._epg_fallback_logo("UK: BBC Two", ""),
            "https://x/bbctwo.png")

    def test_epg_fallback_logo_is_empty_string_not_none_or_error_when_nothing_matches(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        handler = web_mod.Handler.__new__(web_mod.Handler)
        self.assertEqual(handler._epg_fallback_logo("Totally Unmatched Channel", ""), "")

    def test_prewarm_indexes_every_saved_source_so_the_next_check_is_fast(self):
        # Real incident this exists for: Curate's persistent EPG badge
        # fires automatically for the first channel on every page load,
        # and the in-memory guide cache does not survive a run (which
        # routinely outlasts its TTL) or a restart (cold by definition).
        # prewarm_all_sources() is meant to pay that cost ahead of time,
        # in the background, at exactly those two moments.
        from probarr import epgcheck
        self._guide("src-a", [("1", "BBC Two Lon", None)])
        self._guide("src-b", [("2", "BBC Two North", None)])
        epgcheck._cache.clear()
        epgcheck._indexed.clear()
        epgcheck.prewarm_all_sources(self.root, Normalizer())
        self.assertEqual(len(epgcheck._cache), 2)
        self.assertEqual(len(epgcheck._indexed), 2)

    def test_prewarm_is_best_effort_and_never_raises_on_a_bad_source(self):
        from probarr import epgcheck
        from probarr import epgsources
        epgsources.save(self.root, "broken", "file:///no/such/file.xml")
        epgcheck.prewarm_all_sources(self.root, Normalizer())  # must not raise


class TestEpgConsensus(Temp):
    def _guide(self, channels):
        xml = os.path.join(self.root, "guide.xml")
        body = "".join(f'<channel id="{cid}"><display-name>{name}</display-name></channel>'
                       for cid, name in channels)
        with open(xml, "w", encoding="utf-8") as f:
            f.write(f'<?xml version="1.0"?><tv>{body}</tv>')
        from probarr import epgsources
        # KNM fix (probarr-9wl): pathlib.as_uri(), not string concat --
        # "file://" + xml is malformed on Windows (file://B:\...) and
        # fails in urlopen; as_uri() produces a real file:///B:/... URL.
        epgsources.save(self.root, "test-guide", pathlib.Path(xml).as_uri())

    def test_display_clean_leaves_ordinary_names_alone(self):
        from probarr import epgcheck
        self.assertEqual(epgcheck._display_clean("BBC One"), "BBC One")
        self.assertEqual(epgcheck._display_clean("Sky Sports F1"), "Sky Sports F1")

    def test_ordinary_names_are_not_mistaken_for_a_glued_region_suffix(self):
        # Regression: "Sky One" was being stripped to "Sky O" because "NE"
        # (North East) matched its own trailing two letters with no
        # boundary check. Glued region+quality suffixes ("EastHD") DO need
        # to strip with no space, so the fix can't just require a plain
        # word boundary -- it has to tell "glued-on tag" apart from
        # "coincidentally ends in the same letters".
        from probarr import epgcheck
        self.assertEqual(epgcheck._strip_region("Sky One"), "Sky One")
        self.assertEqual(epgcheck._strip_region("BBC One EastHD"), "BBC One")

    def test_unrelated_channels_are_never_grouped_together(self):
        from probarr import epgcheck
        self._guide([("1", "BBC One London"), ("2", "ITV1 London")])
        out = epgcheck.list_channels(self.root, "test-guide", Normalizer())
        self.assertEqual(len(out), 2)
        for row in out:
            self.assertNotIn("alts", row)


class TestBackup(Temp):
    def test_round_trips_config_and_run_state(self):
        from probarr import backup as backup_mod
        providers.save(self.root, "myprov", "http://example.com/list.m3u")
        s = RunStore(self.root, "run1")
        s.write_meta({"run_id": "run1"})  # list_runs() only sees a run via run.json
        s.write_wantlist_raw([{"number": 1, "name": "One", "key": "ONE"}], [])
        s.append({"rec_key": "ONE|a", "channel_key": "ONE", "status": "ok"})
        s.write_selection({"ONE": {"group": "Entertainment"}})

        data = backup_mod.export_tar(self.root)

        fresh = tempfile.mkdtemp(prefix="probarr-test-restore-")
        self.addCleanup(shutil.rmtree, fresh, ignore_errors=True)
        backup_mod.import_tar(fresh, data)

        self.assertEqual(providers.list_all(fresh)[0]["name"], "myprov")
        restored = RunStore(fresh, "run1")
        self.assertEqual(restored.load()[0]["status"], "ok")
        self.assertEqual(restored.read_selection()["ONE"]["group"], "Entertainment")

    def test_refuses_a_path_traversal_member(self):
        import io
        import tarfile
        import uuid
        from probarr import backup as backup_mod
        # A marker name unique to this run, NOT a real system path. The
        # original version escaped to "../../etc/passwd" and then asserted
        # that path did not exist -- which on Linux resolves to the real
        # /etc/passwd and is therefore always true-ish in the wrong
        # direction: the assertion failed on any host whose temp dir sits
        # two levels down (/tmp/xxx), and "passed" on macOS only because
        # its temp dirs are nested deeper. It never tested the property it
        # claimed. Caught by CI the first time the suite was made blocking.
        marker = f"probarr-traversal-{uuid.uuid4().hex}.txt"
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name=f"../../{marker}")
            payload = b"pwned"
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        with self.assertRaises(ValueError):
            backup_mod.import_tar(self.root, buf.getvalue())
        # Nothing written outside root as a side effect of the attempt.
        escaped = os.path.abspath(os.path.join(self.root, "..", "..", marker))
        self.assertFalse(os.path.exists(escaped),
                         f"a traversal member escaped to {escaped}")


class TestAliases(Temp):
    def test_folds_both_sides_so_the_lookup_matches(self):
        aliases_mod.save(self.root, "U&Drama", "drama")
        self.assertEqual(aliases_mod.read(self.root), {"UANDDRAMA": "DRAMA"})

    def test_refuses_an_alias_to_itself(self):
        with self.assertRaises(ValueError):
            aliases_mod.save(self.root, "Drama", "DRAMA")

    def test_delete(self):
        aliases_mod.save(self.root, "U&Drama", "Drama")
        self.assertTrue(aliases_mod.delete(self.root, "u & drama"))
        self.assertEqual(aliases_mod.read(self.root), {})

    def test_an_alias_name_carrying_a_region_prefix_still_matches_the_real_stream(self):
        # Real bug found on a full-codebase review: save() used to fold the
        # raw typed text with plain _fold(), while Normalizer.key() strips
        # region/quality prefixes BEFORE folding a real stream name and
        # only then checks the alias dict -- so an alias name that still
        # carried a prefix (like "UK: Dave") was stored under a key
        # ("UKDAVE") the real lookup ("DAVE", after "UK: " is stripped)
        # could never produce, and the alias silently never fired.
        aliases_mod.save(self.root, "UK: Dave", "U&Dave")
        norm = Normalizer(aliases=aliases_mod.read(self.root))
        self.assertEqual(norm.key("UK: Dave"), norm.key("U&Dave"),
                         "an alias saved with a region prefix must still "
                         "match the real (prefixed) stream name it names")


class TestLineups(Temp):
    def test_partial_update_does_not_blank_other_fields(self):
        lineups.save(self.root, "demo", provider="mybunny", wantlist="uk-demo")
        lineups.save(self.root, "demo", epg="http://guide")
        lu = lineups.get(self.root, "demo")
        self.assertEqual(lu["provider"], "mybunny")
        self.assertEqual(lu["epg"], "http://guide")

    def test_preferences_survive_and_clear(self):
        lineups.save(self.root, "demo")
        lineups.set_preference(self.root, "demo", "BBCONE", group="General",
                               name="BBC One HD")
        self.assertEqual(lineups.preferences(self.root, "demo")["BBCONE"],
                         {"group": "General", "name": "BBC One HD"})
        lineups.set_preference(self.root, "demo", "BBCONE", group=None, name=None)
        self.assertNotIn("BBCONE", lineups.preferences(self.root, "demo"))


class TestCredentials(Temp):
    def test_redaction_hides_every_secret_form(self):
        for spec, secret in [
                ("https://p.tv/get.php?u=bob&p=hunter2", "hunter2"),  # probarr:allow-secret
                ("dispatcharr://admin:s3cret@10.0.0.1:9191", "s3cret"),  # probarr:allow-secret
                ("xtream://user:pw123@panel.tv", "pw123")]:  # probarr:allow-secret
            self.assertNotIn(secret, providers.redact(spec))

    def test_settings_redact_hides_source_and_epg_credentials(self):
        # GET /api/settings must never hand back what write() actually
        # stored -- source/epg may be an xtream://user:pass@host spec.
        secret = "hunter2"  # probarr:allow-secret
        values = settings.write(self.root, {
            "source": "xtream://bob:" + secret + "@panel.tv"})  # probarr:allow-secret
        redacted = settings.redact(values)
        self.assertNotIn(secret, json.dumps(redacted))
        # And the real value must still be recoverable server-side --
        # redact() must not have mutated storage, only the returned copy.
        self.assertIn(secret, settings.read(self.root)["source"])

    def test_settings_redact_leaves_non_secret_fields_untouched(self):
        values = settings.write(self.root, {"concurrency": 3})
        redacted = settings.redact(values)
        self.assertEqual(redacted["concurrency"], 3)


class TestSameOriginWriteGuard(Temp):
    """probarr-tj0: /api/settings and /api/backup/import had no auth at all
    -- any device on the LAN could blind-POST and overwrite provider
    credentials with a bare curl, no session or browser required.
    _same_origin() closes that without needing a login system: a real
    same-origin page write always carries an Origin or Referer naming this
    host, so their absence or mismatch is treated as untrusted.
    """

    def _handler(self, headers):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        h.headers = headers
        return h

    def test_rejects_request_with_no_origin_or_referer(self):
        h = self._handler({"Host": "192.168.1.243:7799"})  # probarr:allow-secret (test fixture IP, not real)
        self.assertFalse(h._same_origin())

    def test_rejects_mismatched_origin(self):
        h = self._handler({"Host": "192.168.1.243:7799",  # probarr:allow-secret (test fixture IP, not real)
                            "Origin": "http://evil.example:1234"})
        self.assertFalse(h._same_origin())

    def test_accepts_matching_origin(self):
        h = self._handler({"Host": "192.168.1.243:7799",  # probarr:allow-secret (test fixture IP, not real)
                            "Origin": "http://192.168.1.243:7799"})  # probarr:allow-secret (test fixture IP, not real)
        self.assertTrue(h._same_origin())

    def test_accepts_matching_referer_when_origin_absent(self):
        h = self._handler({"Host": "192.168.1.243:7799",  # probarr:allow-secret (test fixture IP, not real)
                            "Referer": "http://192.168.1.243:7799/settings"})  # probarr:allow-secret (test fixture IP, not real)
        self.assertTrue(h._same_origin())

    def test_rejects_with_no_host_header_at_all(self):
        h = self._handler({"Origin": "http://192.168.1.243:7799"})  # probarr:allow-secret (test fixture IP, not real)
        self.assertFalse(h._same_origin())

    def test_settings_post_rejects_cross_origin_write(self):
        from probarr import web as web_mod
        from probarr import settings as settings_mod
        h = self._handler({"Host": "192.168.1.243:7799",  # probarr:allow-secret (test fixture IP, not real)
                            "Origin": "http://evil.example"})
        h.path = "/api/settings"
        h.command = "POST"
        payload = json.dumps({"concurrency": 99}).encode("utf-8")
        h.headers["Content-Length"] = str(len(payload))
        import io
        h.rfile = io.BytesIO(payload)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: sent.append((body, code))
        h._do_POST()
        self.assertEqual(sent[0][1], 403)
        # The blind write must never have reached settings.write() at all.
        self.assertNotEqual(settings_mod.read(self.root).get("concurrency"), 99)

    def test_settings_post_accepts_same_origin_write(self):
        from probarr import web as web_mod
        from probarr import settings as settings_mod
        h = self._handler({"Host": "192.168.1.243:7799",  # probarr:allow-secret (test fixture IP, not real)
                            "Origin": "http://192.168.1.243:7799"})  # probarr:allow-secret (test fixture IP, not real)
        h.path = "/api/settings"
        h.command = "POST"
        payload = json.dumps({"concurrency": 5}).encode("utf-8")
        h.headers["Content-Length"] = str(len(payload))
        import io
        h.rfile = io.BytesIO(payload)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: sent.append((body, code))
        h._do_POST()
        self.assertEqual(sent[0][1], 200)
        self.assertEqual(settings_mod.read(self.root)["concurrency"], 5)


class TestKeydownGuardsEveryModal(unittest.TestCase):
    """Real bug found on a full-codebase review: the document-level keydown
    handler only checked the lightbox and clip viewer before processing
    j/k/arrow channel navigation -- Check EPG, watermark, groups, import
    and catalog modals were not checked, so a hotkey pressed while one was
    open silently changed `current` underneath it. Only a live browser can
    exercise the actual event flow (see this commit's manual verification
    against the running app); this locks in the source-level guard so a
    future edit can't silently narrow it back to naming specific modals.
    """

    def test_the_generic_any_modal_open_guard_is_present(self):
        from probarr import curate
        # Must appear BEFORE the j/k/arrow navigation branch, and must be
        # a generic "any .modal.on" check -- not a per-id list, which is
        # exactly the shape that missed every modal except two.
        idx_guard = curate.HTML.index('document.querySelector(".modal.on")')
        idx_nav = curate.HTML.index('e.key==="ArrowDown"||e.key==="j"')
        self.assertLess(idx_guard, idx_nav,
                        "the modal-open guard must run before hotkey navigation")


class TestCatalogCacheThreadSafety(Temp):
    """Real bug found on a full-codebase review: _catalog_cache is a
    CLASS-level dict shared by every ThreadingHTTPServer request thread.
    The old code unconditionally called self._catalog_cache.clear() on
    EVERY cache miss for ANY spec -- so a concurrent request for a second
    provider's catalogue wiped a first provider's already-cached, still
    valid entry, forcing it to be silently rebuilt (a full re-parse of a
    potentially 55k-entry playlist) on its very next lookup even though
    nothing about it had changed or gone stale. Fixed to evict only the
    OTHER (differing) keys under a lock, scoped to what's actually stale.
    """

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        web_mod.Handler._catalog_cache = {}
        h = web_mod.Handler.__new__(web_mod.Handler)
        h._norm = lambda: __import__(
            "probarr.normalize", fromlist=["Normalizer"]).Normalizer()
        return h

    def test_a_second_specs_build_does_not_evict_the_first(self):
        from probarr.sources.base import Stream
        h = self._handler()
        calls = []
        def fake_load(spec):
            calls.append(spec)
            return [Stream(id=spec, name=spec, url=f"http://x/{spec}")]
        h._load_source_cached = fake_load

        store_a = RunStore(self.root, "run-a", create=True)
        store_a.write_meta({"source": "http://provider-a/list.m3u"})
        store_b = RunStore(self.root, "run-b", create=True)
        store_b.write_meta({"source": "http://provider-b/list.m3u"})

        h._catalog_pools(store_a)   # primes the cache for A
        self.assertEqual(calls, ["http://provider-a/list.m3u"])

        h._catalog_pools(store_b)   # a miss for a DIFFERENT spec
        self.assertEqual(len(calls), 2, "B should have been built once")

        # The real assertion: looking A up again must be a cache HIT --
        # the old code's blanket clear() during B's build would have
        # evicted A, forcing this call to rebuild it from scratch.
        h._catalog_pools(store_a)
        self.assertEqual(len(calls), 2,
                         "A was rebuilt even though nothing about it "
                         "changed -- B's miss must not evict A's entry")

    def test_concurrent_builds_for_two_specs_each_land_correctly(self):
        from probarr.sources.base import Stream
        h = self._handler()
        barrier = threading.Barrier(2)
        def fake_load(spec):
            barrier.wait(timeout=5)   # force both threads to overlap
            return [Stream(id=spec, name=spec, url=f"http://x/{spec}")]
        h._load_source_cached = fake_load

        store_a = RunStore(self.root, "run-a", create=True)
        store_a.write_meta({"source": "http://provider-a/list.m3u"})
        store_b = RunStore(self.root, "run-b", create=True)
        store_b.write_meta({"source": "http://provider-b/list.m3u"})

        results = {}
        def go(name, store):
            results[name] = h._catalog_pools(store)

        t1 = threading.Thread(target=go, args=("a", store_a))
        t2 = threading.Thread(target=go, args=("b", store_b))
        t1.start(); t2.start()
        t1.join(); t2.join()

        self.assertEqual(len(h._catalog_cache), 2,
                         "both specs must remain cached after the race, "
                         "not just whichever finished last")
        names_a = {s.name for pool in results["a"].values() for s in pool}
        names_b = {s.name for pool in results["b"].values() for s in pool}
        self.assertEqual(names_a, {"http://provider-a/list.m3u"})
        self.assertEqual(names_b, {"http://provider-b/list.m3u"})


class TestCarryForwardScopedPerChannel(Temp):
    """Real bug found on a full-codebase review: _carry_forward_fresh()
    matched a prior record's stream_id against a set flattened across
    EVERY channel's pool, not the specific channel that record belongs to.
    A provider listing the same URL under two channel names (documented
    elsewhere in this codebase as a real thing that happens) let a stale
    verdict for a channel OUTSIDE this run's scope carry forward anyway,
    just because some other, in-scope channel happened to share the id.
    """

    def _lineup_run(self, run_id, lineup, channel_key, stream_id, status,
                    age_hours=1):
        from probarr.store import RunStore
        store = RunStore(self.root, run_id, create=True)
        store.write_meta({"lineup": lineup, "run_state": "done"})
        store.append({"rec_key": f"{channel_key}|{stream_id}",
                     "channel_key": channel_key, "stream_id": stream_id,
                     "status": status,
                     "probed_at": time.time() - age_hours * 3600})
        return store

    def test_a_shared_stream_id_does_not_carry_forward_an_out_of_scope_channel(self):
        from probarr import runner
        from probarr.settings import write as write_settings
        from probarr.sources.base import Stream
        write_settings(self.root, {"freshness_hours": 24})

        # Prior run had BOTH channels, sharing one stream id (the same URL
        # listed under two names -- confirmed real by verify.py's own docs).
        prior = self._lineup_run("run-prior", "LU", "INSCOPE", "shared:1", "ok")
        prior.append({"rec_key": "OUTOFSCOPE|shared:1", "channel_key": "OUTOFSCOPE",
                     "stream_id": "shared:1", "status": "ok",
                     "probed_at": time.time() - 3600})

        # This run's pools only carry INSCOPE -- OUTOFSCOPE was excluded
        # (e.g. by only_channels/min_candidates/limit_channels upstream).
        current = RunStore(self.root, "run-current", create=True)
        current.write_meta({"lineup": "LU", "run_state": "running"})
        pools = {"INSCOPE": [Stream(id="shared:1", name="x", url="http://x/1")]}

        runner._carry_forward_fresh(self.root, current, "LU", pools, lambda m: None)

        rows = current.load()
        keys = {r["channel_key"] for r in rows}
        self.assertIn("INSCOPE", keys)
        self.assertNotIn("OUTOFSCOPE", keys,
                         "a channel outside this run's scope must not gain a "
                         "carried-forward record just because it shares a "
                         "stream id with an in-scope channel")


class TestXtreamCategoryLookupSurvivesNumericIds(unittest.TestCase):
    """Real bug found on a full-codebase review: the category-name dict was
    keyed by category_id's native JSON type, but the per-stream lookup
    always cast to str -- a panel emitting category_id as a JSON number
    (not all of them agree on this) meant every lookup missed and every
    stream from that source silently lost its group.
    """

    def test_a_numeric_category_id_still_resolves_a_group_name(self):
        from probarr.sources.xtream import Xtream
        x = Xtream("http://fake", "u", "p")
        x._api = lambda action, **kw: (
            [{"category_id": 5, "category_name": "Sport"}]
            if action == "get_live_categories" else
            [{"stream_id": 1, "name": "Sky Sports", "category_id": 5}])
        streams = x.live_streams()
        self.assertEqual(streams[0].group, "Sport")


class TestGuideKeepsAWindowSpanningProgramme(Temp):
    """Real bug found on a full-codebase review: Guide.load()'s retention
    test kept a programme only if one of its endpoints fell inside the
    retention window -- a programme that starts BEFORE the window and ends
    AFTER it (fully covering it, e.g. a long all-day placeholder block some
    aggregators emit for sparsely-listed channels) satisfied neither
    clause and was silently dropped even though it genuinely covers `at`.
    """

    def test_a_programme_spanning_the_whole_window_is_kept(self):
        import datetime as _dt
        from probarr.epg import Guide
        at = _dt.datetime.now(_dt.timezone.utc)
        start = (at - _dt.timedelta(hours=100)).strftime("%Y%m%d%H%M%S +0000")
        stop = (at + _dt.timedelta(hours=100)).strftime("%Y%m%d%H%M%S +0000")
        xml = os.path.join(self.root, "guide.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0"?><tv><channel id="c1">'
                   '<display-name>X</display-name></channel>'
                   f'<programme channel="c1" start="{start}" stop="{stop}">'
                   '<title>All Day</title></programme></tv>')
        # window_hours=6 -- the window is +/-6h around `at`, well inside
        # this programme's 200-hour span on both sides.
        g = Guide.load(xml, window_hours=6, at=at)
        now = g.now_playing("c1", at)
        self.assertIsNotNone(now,
                             "a programme spanning the whole retention "
                             "window must not be dropped by it")
        self.assertEqual(now["title"], "All Day")


class TestGuideRefusesAnSdHdNameCollision(unittest.TestCase):
    """Real reported bug: a combined guide carries separate SD and HD rows
    for the same channel (confirmed live: sheffield_hd.xml's "Sky Atlantic"
    / "Sky Atlantic HD", each its own <channel> id with its own independent
    programme list) -- once "HD" strips as a quality tag both normalise to
    the same key, and a bare setdefault() silently kept whichever parsed
    first. If Dispatcharr happened to be linked to the OTHER one of the
    pair, every check against this guide reported a permanent false
    mismatch, because the SD/HD copies simply drift out of sync with each
    other from feed processing, not because either link was wrong.

    Resolved automatically now (HD preferred) when the collision is
    PURELY a quality tier -- the colliding names are otherwise identical.
    A collision from any other cause (different regions, a genuine
    coincidence) still refuses exactly as before; that distinction is the
    whole point, not a loosening of it."""

    def _guide(self, entries):
        """entries: [(channel_id, display_name)]"""
        from probarr.epg import Guide
        g = Guide()
        for cid, name in entries:
            g.display_names.setdefault(cid, []).append(name)
        return g

    def test_an_sd_hd_pair_auto_resolves_to_the_hd_copy(self):
        from probarr.normalize import Normalizer
        g = self._guide([("1412.sky.uk", "Sky Atlantic"),
                         ("4053.sky.uk", "Sky Atlantic HD")])
        g.build_name_index(Normalizer())
        self.assertEqual(g.resolve(None, "Sky Atlantic", Normalizer()), "4053.sky.uk")

    def test_a_genuinely_different_channel_collision_still_refuses(self):
        # Two names that collide only because key() strips region markers
        # -- NOT a quality-tier duplicate, and must keep refusing exactly
        # as before. Auto-resolving this would be the same wrong-guess
        # this was built to avoid, just for a different root cause.
        from probarr.normalize import Normalizer
        g = self._guide([("uk.sky.uk", "UK: Sky News"),
                         ("us.sky.uk", "US: Sky News")])
        g.build_name_index(Normalizer())
        self.assertIsNone(g.resolve(None, "Sky News", Normalizer()))

    def test_two_hd_tagged_entries_in_one_group_still_refuses(self):
        # Not a clean SD/HD pair -- two separately-HD-tagged rows (a merged
        # feed's own duplicate, say). "Exactly one HD candidate" is the
        # actual rule, not "prefer whichever HD one comes first".
        from probarr.normalize import Normalizer
        g = self._guide([("a", "Sky Atlantic HD"), ("b", "Sky Atlantic HD ")])
        g.build_name_index(Normalizer())
        self.assertIsNone(g.resolve(None, "Sky Atlantic", Normalizer()))

    def test_an_unambiguous_channel_still_resolves_fine(self):
        from probarr.normalize import Normalizer
        g = self._guide([("1412.sky.uk", "Sky Atlantic"),
                         ("4053.sky.uk", "Sky Atlantic HD"),
                         ("2201.sky.uk", "Sky Witness")])
        g.build_name_index(Normalizer())
        self.assertEqual(g.resolve(None, "Sky Witness", Normalizer()), "2201.sky.uk")

    def test_an_exact_tvg_id_overrides_the_hd_preference(self):
        # resolve()'s tvg_id branch is checked first and needs no name
        # index at all -- an explicit id must win even over the auto
        # HD-preference, e.g. an operator who deliberately wants the SD
        # feed linked (a slower connection, say).
        from probarr.normalize import Normalizer
        g = self._guide([("1412.sky.uk", "Sky Atlantic"),
                         ("4053.sky.uk", "Sky Atlantic HD")])
        g.build_name_index(Normalizer())
        self.assertEqual(g.resolve("1412.sky.uk", "Sky Atlantic", Normalizer()),
                         "1412.sky.uk")

    def test_the_fuzzy_fallback_does_not_resolve_to_the_channels_own_plus1(self):
        # Real reported bug, the direct sequel to the SD/HD fix above: a
        # genuinely ambiguous (non-quality) collision that falls through
        # to the fuzzy path used to find "Sky Atlantic+1" as the only
        # remaining startswith() candidate and resolve straight to it --
        # normalizer.key("Sky Atlantic+1") IS a prefix match for "Sky
        # Atlantic", even though a +1 channel is an hour-shifted,
        # genuinely different schedule, not a spelling variant.
        from probarr.normalize import Normalizer
        g = self._guide([("uk.sky.uk", "UK: Sky Atlantic"),
                         ("us.sky.uk", "US: Sky Atlantic"),
                         ("1413.sky.uk", "Sky Atlantic+1")])
        g.build_name_index(Normalizer())
        self.assertIsNone(g.resolve(None, "Sky Atlantic", Normalizer()))

    def test_a_plus1_query_can_still_resolve_to_its_own_plus1_entry(self):
        # The timeshift guard must not be so broad it blocks a genuine
        # "+1" channel from ever resolving at all.
        from probarr.normalize import Normalizer
        g = self._guide([("1412.sky.uk", "Sky Atlantic"),
                         ("1413.sky.uk", "Sky Atlantic+1")])
        g.build_name_index(Normalizer())
        self.assertEqual(g.resolve(None, "Sky Atlantic+1", Normalizer()), "1413.sky.uk")


class TestDoublePushIsRejected(Temp):
    """Real bug found on a full-codebase review: the "is a push already
    running" check and the actual claim (writing push_status state=running)
    used to be separated by several lines of unrelated processing with
    nothing atomic between them -- two near-simultaneous requests (a
    double-click, two open tabs) could both read "not running" and both
    spawn a background export thread against the same Dispatcharr instance.
    """

    def _setup_run(self):
        from probarr.store import RunStore
        from probarr import providers as providers_mod
        store = RunStore(self.root, "run1", create=True)
        store.append({"rec_key": "BBCONE|s1", "channel_key": "BBCONE",
                     "stream_id": "s1", "status": "ok", "url": "http://x/1",
                     "url_redacted": "", "group": "", "logo": "",
                     "tvg_id": "", "probed_at": 1})
        store.write_wantlist_raw(
            [{"key": "BBCONE", "number": 101, "name": "BBC One"}], [])
        providers_mod.save(self.root, "dp1",
                          "dispatcharr://u:p@192.168.1.1:9191")  # probarr:allow-secret (test fixture)
        return store

    def test_two_near_simultaneous_pushes_only_one_is_accepted(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        web_mod.Handler._push_locks = {}
        self._setup_run()

        orig_read = None

        def make_handler():
            h = web_mod.Handler.__new__(web_mod.Handler)
            sent = []
            h._send = lambda body, ctype="application/json", code=200: (
                sent.append((code, body)), sent)[-1]
            return h, sent

        def racy_read_push_status(store_self):
            # A real delay between "check" and the caller's subsequent
            # claim -- this is what widens the pre-fix vulnerable window
            # (nothing serialized the two) without deadlocking post-fix
            # (the per-run lock now means only one thread is ever in here
            # concurrently in the first place; the other simply waits for
            # the lock, and by the time it gets in, the claim already
            # landed).
            time.sleep(0.05)
            return orig_read(store_self)

        from probarr.store import RunStore
        orig_read = RunStore.read_push_status
        results = []
        def go():
            h, sent = make_handler()
            h._export_dispatcharr("run1", {"provider": "dp1",
                                          "fallback_mode": "native"})
            results.append(sent[0][0] if sent else None)

        # Patched ONCE, around both threads -- not per-thread. Two threads
        # each entering their own `with unittest.mock.patch.object(...)` on
        # the SAME class attribute is racy: patch.object's __enter__/__exit__
        # save-then-restore by plain attribute assignment, so if thread A's
        # __exit__ runs between thread B's __enter__ (saves A's patched
        # value as "the original") and B's own __exit__, B restores the
        # class to A's patched value instead of the true original --
        # permanently monkey-patching Handler._run_export to this no-op
        # lambda for the rest of the test PROCESS, not just this test. Real
        # bug found this way: every later test that called the real
        # _run_export and asserted on it silently saw the no-op instead,
        # under whichever runner happened to execute this test first.
        with unittest.mock.patch.object(
                RunStore, "read_push_status", racy_read_push_status), \
            unittest.mock.patch.object(
                web_mod.Handler, "_run_export", lambda self, *a, **k: None):
            results_lock_threads = [threading.Thread(target=go),
                                    threading.Thread(target=go)]
            for th in results_lock_threads:
                th.start()
            for th in results_lock_threads:
                th.join()

        self.assertEqual(sorted(results), [200, 409],
                         "exactly one concurrent push must be accepted and "
                         "the other rejected as already running -- both "
                         "succeeding means the double-push race is back")


class TestWantlistWritesAreSerializedPerRun(Temp):
    """Real bug found on a full-codebase review: _reorder_group,
    _swap_numbers, _catalog_add and _rename_channel each read the
    wantlist, mutated an in-memory copy, and wrote it back, with nothing
    serializing two such requests landing close together. Whichever wrote
    second silently discarded the first's change even though both request
    handlers reported {"ok": true}. Reproduced here with two concurrent
    renames of two DIFFERENT channels in the same run -- both must survive.
    """

    def test_two_concurrent_renames_do_not_clobber_each_other(self):
        from probarr import web as web_mod
        from probarr.store import RunStore
        web_mod.Handler.root = self.root
        web_mod.Handler._wantlist_locks = {}

        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw(
            [{"key": "A", "number": 1, "name": "A"},
             {"key": "B", "number": 2, "name": "B"}], [])
        store.append({"rec_key": "A|s1", "channel_key": "A", "stream_id": "s1",
                     "status": "ok"})

        orig_read = RunStore.read_wantlist
        def slow_read(self_store):
            # Widens the read-modify-write window so two concurrent
            # requests reliably both read the pre-rename wantlist -- the
            # exact condition needed for the lost-update bug to fire.
            result = orig_read(self_store)
            time.sleep(0.05)
            return result

        def do_rename(key, name):
            h = web_mod.Handler.__new__(web_mod.Handler)
            sent = []
            h._send = lambda body, ctype="application/json", code=200: sent.append(body)
            with unittest.mock.patch.object(RunStore, "read_wantlist", slow_read):
                h._rename_channel("run1", {"channel_key": key, "name": name})

        t1 = threading.Thread(target=do_rename, args=("A", "Renamed A"))
        t2 = threading.Thread(target=do_rename, args=("B", "Renamed B"))
        t1.start(); t2.start()
        t1.join(); t2.join()

        wanted = {w["key"]: w["name"] for w in
                 RunStore(self.root, "run1").read_wantlist()["wanted"]}
        self.assertEqual(wanted, {"A": "Renamed A", "B": "Renamed B"},
                         "one rename was silently lost to the other's write")


class TestRenameChannelWithNoWantlistEntry(Temp):
    """Same fix as TestRenumberChannel's
    test_sets_a_number_on_a_channel_that_has_no_wantlist_entry_at_all,
    applied to _rename_channel: a channel Curate lists from probe results
    alone (no wantlist entry yet) should be addable by renaming it too,
    not just by numbering it."""

    def test_renaming_creates_the_missing_wantlist_entry(self):
        from probarr import web as web_mod
        from probarr.store import RunStore
        web_mod.Handler.root = self.root
        web_mod.Handler._wantlist_locks = {}
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw([], [])
        store.append({"rec_key": "A|s1", "channel_key": "A", "stream_id": "s1",
                     "name": "Discovery FHD", "status": "ok"})
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: sent.append((code, body))
        h._rename_channel("run1", {"channel_key": "A", "name": "Discovery"})
        self.assertEqual(sent[-1][0], 200, sent[-1])
        wanted = RunStore(self.root, "run1").read_wantlist()["wanted"]
        self.assertEqual(len(wanted), 1)
        self.assertEqual(wanted[0]["name"], "Discovery")
        self.assertEqual(wanted[0]["key"], "A")


class TestClaimIntoRun(Temp):
    """Real user-reported bug: assigning an "Unclaimed" Dispatcharr channel
    to the run that already curates it -- the single most common case,
    since Unclaimed's whole reason to exist is channels probarr pushed
    before the claims system existed -- failed with "a channel with this
    name is already in this run". That was true and useless: the fix is
    to claim the existing wantlist entry in place, not to require a
    brand new one."""

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        web_mod.Handler._wantlist_locks = {}
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: (
            sent.append((code, body)), sent)[-1]
        return h, sent

    def test_claiming_a_channel_already_in_the_run_relinks_instead_of_erroring(self):
        from probarr import claims
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw(
            [{"key": "BBCONE", "number": 101, "name": "BBC One"}], [])
        store.append({"rec_key": "BBCONE|s1", "channel_key": "BBCONE",
                     "stream_id": "s1", "status": "ok"})
        h, sent = self._handler()
        h._claim_into_run("run1", {"dispatcharr_id": 55, "name": "BBC One",
                                   "number": 101})
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        wanted = RunStore(self.root, "run1").read_wantlist()["wanted"]
        self.assertEqual(len(wanted), 1,
                         "the existing entry must be reused, not duplicated")
        self.assertTrue(claims.is_claimed(self.root, 55))

    def test_relinking_backfills_a_missing_number_but_never_overwrites_one(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw(
            [{"key": "BBCONE", "number": None, "name": "BBC One"}], [])
        store.append({"rec_key": "BBCONE|s1", "channel_key": "BBCONE",
                     "stream_id": "s1", "status": "ok"})
        h, sent = self._handler()
        h._claim_into_run("run1", {"dispatcharr_id": 55, "name": "BBC One",
                                   "number": 101})
        wanted = RunStore(self.root, "run1").read_wantlist()["wanted"]
        self.assertEqual(wanted[0]["number"], 101)

        # A second claim with a DIFFERENT incoming number must not clobber
        # the number the run already has -- that's what channel-renumber
        # is for, deliberately, not an implicit side effect of claiming.
        h2, sent2 = self._handler()
        h2._claim_into_run("run1", {"dispatcharr_id": 56, "name": "BBC One",
                                    "number": 999})
        wanted2 = RunStore(self.root, "run1").read_wantlist()["wanted"]
        self.assertEqual(wanted2[0]["number"], 101)

    def test_a_genuinely_new_channel_is_still_appended(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw(
            [{"key": "BBCONE", "number": 101, "name": "BBC One"}], [])
        store.append({"rec_key": "BBCONE|s1", "channel_key": "BBCONE",
                     "stream_id": "s1", "status": "ok"})
        h, sent = self._handler()
        h._claim_into_run("run1", {"dispatcharr_id": 77, "name": "ITV",
                                   "number": 103})
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        wanted = {w["key"]: w for w in RunStore(self.root, "run1").read_wantlist()["wanted"]}
        self.assertEqual(len(wanted), 2)
        self.assertEqual(wanted["ITV"]["number"], 103)


class TestDeleteUnclaimedChannel(Temp):
    """Real user request: Unclaimed needs a way to delete a channel from
    Dispatcharr outright, not just assign it somewhere. Deliberately
    immediate rather than staged through a push preview -- see
    _delete_unclaimed_channel's docstring for why an unclaimed channel has
    no run/selection to stage the deletion against in the first place."""

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: (
            sent.append((code, body)), sent)[-1]
        return h, sent

    def _fake_client(self, calls):
        client = unittest.mock.MagicMock()
        def fake_api(method, path):
            calls.append((method, path))
            return {}
        client.api.side_effect = fake_api
        return client

    def test_deletes_the_channel_and_clears_any_stale_claim(self):
        import json
        from probarr import web as web_mod, providers, claims
        providers.save(self.root, "dp", "dispatcharr://u:p@host:9191")
        claims.claim(self.root, 55, "OLDKEY", "Old Name")
        calls = []
        h, sent = self._handler()
        with unittest.mock.patch.object(web_mod, "client_from_spec",
                                        return_value=self._fake_client(calls)):
            h._delete_unclaimed_channel({"provider": "dp", "dispatcharr_id": 55})
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        self.assertEqual(calls, [("DELETE", "/api/channels/channels/55/")])
        self.assertFalse(claims.is_claimed(self.root, 55))

    def test_rejects_a_provider_that_is_not_dispatcharr(self):
        from probarr import providers
        providers.save(self.root, "iptv", "http://example/x.m3u")
        h, sent = self._handler()
        h._delete_unclaimed_channel({"provider": "iptv", "dispatcharr_id": 55})
        self.assertEqual(sent[-1][0], 404)

    def test_reports_a_dispatcharr_error_without_crashing(self):
        from probarr import web as web_mod, providers
        providers.save(self.root, "dp", "dispatcharr://u:p@host:9191")
        client = unittest.mock.MagicMock()
        client.api.side_effect = RuntimeError("boom")
        h, sent = self._handler()
        with unittest.mock.patch.object(web_mod, "client_from_spec", return_value=client):
            h._delete_unclaimed_channel({"provider": "dp", "dispatcharr_id": 55})
        self.assertEqual(sent[-1][0], 502)


class TestDeleteUnclaimedChannelsBulk(Temp):

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: (
            sent.append((code, body)), sent)[-1]
        return h, sent

    def test_deletes_several_and_reports_errors_separately(self):
        import json
        from probarr import web as web_mod, providers, claims
        providers.save(self.root, "dp", "dispatcharr://u:p@host:9191")
        claims.claim(self.root, 1, "A", "A")
        claims.claim(self.root, 2, "B", "B")
        calls = []
        client = unittest.mock.MagicMock()
        def fake_api(method, path):
            calls.append((method, path))
            if "/2/" in path:
                raise RuntimeError("nope")
            return {}
        client.api.side_effect = fake_api
        h, sent = self._handler()
        with unittest.mock.patch.object(web_mod, "client_from_spec", return_value=client):
            h._delete_unclaimed_channels_bulk({"provider": "dp",
                                               "dispatcharr_ids": [1, 2]})
        d = json.loads(sent[-1][1])
        self.assertEqual(d["deleted"], 1)
        self.assertEqual(len(d["errors"]), 1)
        self.assertEqual(d["errors"][0]["dispatcharr_id"], 2)
        self.assertFalse(claims.is_claimed(self.root, 1))
        self.assertTrue(claims.is_claimed(self.root, 2),
                        "a channel whose delete FAILED must keep its claim")

    def test_requires_a_non_empty_id_list(self):
        from probarr import providers
        providers.save(self.root, "dp", "dispatcharr://u:p@host:9191")
        h, sent = self._handler()
        h._delete_unclaimed_channels_bulk({"provider": "dp", "dispatcharr_ids": []})
        self.assertEqual(sent[-1][0], 400)


class TestClaimIntoRunBulk(Temp):
    """The "select 500 channels, assign them all" case -- one request
    instead of one per channel, sharing the same relink-or-append logic
    as the single-channel endpoint via _claim_one_into_wantlist."""

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        web_mod.Handler._wantlist_locks = {}
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: (
            sent.append((code, body)), sent)[-1]
        return h, sent

    def test_assigns_a_mix_of_relinked_and_new_channels_in_one_call(self):
        import json
        from probarr import claims
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw(
            [{"key": "BBCONE", "number": 101, "name": "BBC One"}], [])
        store.append({"rec_key": "BBCONE|s1", "channel_key": "BBCONE",
                     "stream_id": "s1", "status": "ok"})
        h, sent = self._handler()
        h._claim_into_run_bulk("run1", {"channels": [
            {"dispatcharr_id": 1, "name": "BBC One", "number": 101},
            {"dispatcharr_id": 2, "name": "ITV", "number": 103},
            {"dispatcharr_id": 3, "name": "Channel 4", "number": 104},
        ]})
        code, body = sent[-1]
        d = json.loads(body)
        self.assertEqual(code, 200, body)
        self.assertEqual(d["assigned"], 3)
        self.assertEqual(d["relinked"], 1)
        self.assertEqual(d["errors"], [])
        wanted = {w["key"]: w for w in RunStore(self.root, "run1").read_wantlist()["wanted"]}
        self.assertEqual(len(wanted), 3,
                         "the already-curated BBC One must be relinked, not duplicated")
        self.assertEqual(wanted["ITV"]["number"], 103)
        self.assertEqual(wanted["CHANNEL4"]["number"], 104)
        for did in (1, 2, 3):
            self.assertTrue(claims.is_claimed(self.root, did))

    def test_one_bad_entry_does_not_block_the_rest_of_the_batch(self):
        import json
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw([], [])
        store.append({"rec_key": "X|s1", "channel_key": "X", "stream_id": "s1",
                     "status": "ok"})
        h, sent = self._handler()
        h._claim_into_run_bulk("run1", {"channels": [
            {"dispatcharr_id": 1, "name": "ITV", "number": 103},
            {"dispatcharr_id": None, "name": "Broken", "number": 999},
        ]})
        d = json.loads(sent[-1][1])
        self.assertEqual(d["assigned"], 1)
        self.assertEqual(len(d["errors"]), 1)
        self.assertEqual(d["errors"][0]["name"], "Broken")
        wanted = RunStore(self.root, "run1").read_wantlist()["wanted"]
        self.assertEqual(len(wanted), 1)
        self.assertEqual(wanted[0]["key"], "ITV")

    def test_requires_a_non_empty_channel_list(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.append({"rec_key": "X|s1", "channel_key": "X", "stream_id": "s1",
                     "status": "ok"})
        h, sent = self._handler()
        h._claim_into_run_bulk("run1", {"channels": []})
        self.assertEqual(sent[-1][0], 400)


class TestRenumberChannel(Temp):
    """Curate now shows a channel with no number in bright red (it would
    otherwise be silently dropped from every export by _resolve_curated in
    web.py) and lets it be fixed in place, mirroring the existing rename
    endpoint. _renumber_channel is the server half of that."""

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        web_mod.Handler._wantlist_locks = {}
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: (
            sent.append((code, body)), sent)[-1]
        return h, sent

    def test_sets_a_missing_number(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw(
            [{"key": "A", "number": None, "name": "A"}], [])
        store.append({"rec_key": "A|s1", "channel_key": "A", "stream_id": "s1",
                     "status": "ok"})
        h, sent = self._handler()
        h._renumber_channel("run1", {"channel_key": "A", "number": 101})
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        wanted = RunStore(self.root, "run1").read_wantlist()["wanted"]
        self.assertEqual(wanted[0]["number"], 101,
                         "the new number was not written back to the wantlist")

    def test_rejects_a_number_already_used_by_another_channel(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw(
            [{"key": "A", "number": None, "name": "A"},
             {"key": "B", "number": 202, "name": "B"}], [])
        store.append({"rec_key": "A|s1", "channel_key": "A", "stream_id": "s1",
                     "status": "ok"})
        h, sent = self._handler()
        h._renumber_channel("run1", {"channel_key": "A", "number": 202})
        code, body = sent[-1]
        self.assertEqual(code, 409,
                         "assigning a number another channel already owns must "
                         "be rejected, not silently overwrite that channel's "
                         "identity in Dispatcharr")
        wanted = {w["key"]: w["number"] for w in
                 RunStore(self.root, "run1").read_wantlist()["wanted"]}
        self.assertIsNone(wanted["A"])

    def test_rejects_non_positive_numbers(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw([{"key": "A", "number": None, "name": "A"}], [])
        store.append({"rec_key": "A|s1", "channel_key": "A", "stream_id": "s1",
                     "status": "ok"})
        h, sent = self._handler()
        h._renumber_channel("run1", {"channel_key": "A", "number": 0})
        self.assertEqual(sent[-1][0], 400)
        h._renumber_channel("run1", {"channel_key": "A", "number": "not-a-number"})
        self.assertEqual(sent[-1][0], 400)

    def test_sets_a_number_on_a_channel_that_has_no_wantlist_entry_at_all(self):
        """Real bug: Curate lists a channel built purely from probe results
        when it has candidates but never made it into the wantlist (see
        _resolve_curated's docstring) -- exactly the shape of channel this
        whole feature exists to fix. Setting its number 404'd with "channel
        not in this run's wantlist", which is true but useless: the curator
        is looking straight at it in the UI and has no other way to add it.
        """
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw([], [])
        store.append({"rec_key": "A|s1", "channel_key": "A", "stream_id": "s1",
                     "name": "Discovery FHD", "status": "ok"})
        h, sent = self._handler()
        h._renumber_channel("run1", {"channel_key": "A", "number": 301})
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        wanted = RunStore(self.root, "run1").read_wantlist()["wanted"]
        self.assertEqual(len(wanted), 1)
        self.assertEqual(wanted[0]["number"], 301)
        self.assertEqual(wanted[0]["key"], "A")

    def test_still_404s_for_a_channel_with_no_probe_results_either(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw([], [])
        store.append({"rec_key": "X|s1", "channel_key": "X", "stream_id": "s1",
                     "status": "ok"})
        h, sent = self._handler()
        h._renumber_channel("run1", {"channel_key": "does-not-exist", "number": 5})
        self.assertEqual(sent[-1][0], 404)

    def test_warns_when_the_number_already_belongs_to_a_live_dispatcharr_channel(self):
        """Real bug found in a fresh-user walkthrough: push-preview already
        refuses a genuine number collision (see dispatcharr_export._conflict),
        but nothing said so until the very end of the flow -- the curator
        numbered ten channels, only to discover on "Preview changes" that
        3007 was already "TNT Sports 6" in Dispatcharr. Setting the number
        must surface that collision immediately, right where it's set.
        """
        from probarr.store import RunStore
        from probarr import web as web_mod, providers
        providers.save(self.root, "dp", "dispatcharr://u:p@host:9191")
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw([{"key": "A", "number": None, "name": "A"}], [])
        store.append({"rec_key": "A|s1", "channel_key": "A", "stream_id": "s1",
                     "status": "ok"})
        client = unittest.mock.MagicMock()
        client.channels.return_value = [
            {"id": 9, "channel_number": 3007.0, "name": "TNT Sports 6"}]
        h, sent = self._handler()
        with unittest.mock.patch.object(web_mod, "client_from_spec", return_value=client):
            h._renumber_channel("run1", {"channel_key": "A", "number": 3007})
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        payload = json.loads(body)
        self.assertEqual(payload["dispatcharr_collision"], "TNT Sports 6")

    def test_no_warning_when_the_number_is_actually_free(self):
        from probarr.store import RunStore
        from probarr import web as web_mod, providers
        providers.save(self.root, "dp", "dispatcharr://u:p@host:9191")
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw([{"key": "A", "number": None, "name": "A"}], [])
        store.append({"rec_key": "A|s1", "channel_key": "A", "stream_id": "s1",
                     "status": "ok"})
        client = unittest.mock.MagicMock()
        client.channels.return_value = [
            {"id": 9, "channel_number": 5000.0, "name": "Something Else"}]
        h, sent = self._handler()
        with unittest.mock.patch.object(web_mod, "client_from_spec", return_value=client):
            h._renumber_channel("run1", {"channel_key": "A", "number": 3007})
        payload = json.loads(sent[-1][1])
        self.assertIsNone(payload["dispatcharr_collision"])

    def test_no_warning_when_this_run_already_claimed_that_dispatcharr_channel(self):
        """A number claimed as an intentional relink (see claims.py) is not
        a collision -- it's the same channel, just not yet tagged."""
        from probarr.store import RunStore
        from probarr import web as web_mod, providers, claims
        providers.save(self.root, "dp", "dispatcharr://u:p@host:9191")
        claims.claim(self.root, 9, "A", "A")
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw([{"key": "A", "number": None, "name": "A"}], [])
        store.append({"rec_key": "A|s1", "channel_key": "A", "stream_id": "s1",
                     "status": "ok"})
        client = unittest.mock.MagicMock()
        client.channels.return_value = [
            {"id": 9, "channel_number": 3007.0, "name": "A (already claimed)"}]
        h, sent = self._handler()
        with unittest.mock.patch.object(web_mod, "client_from_spec", return_value=client):
            h._renumber_channel("run1", {"channel_key": "A", "number": 3007})
        payload = json.loads(sent[-1][1])
        self.assertIsNone(payload["dispatcharr_collision"])

    def test_promotes_the_number_to_the_lineup_so_it_survives_a_rebuild(self):
        """Without this, a number set by hand in Curate would revert to
        unset the next time the wantlist is rebuilt from the provider --
        the exact loss the rename endpoint already avoids for names."""
        from probarr.store import RunStore
        from probarr import lineups as lineups_mod
        lineups_mod.save(self.root, "my-lineup", provider="p1")
        store = RunStore(self.root, "run1", create=True)
        store.write_meta({"lineup": "my-lineup"})
        store.write_wantlist_raw(
            [{"key": "A", "number": None, "name": "A"}], [])
        store.append({"rec_key": "A|s1", "channel_key": "A", "stream_id": "s1",
                     "status": "ok"})
        h, sent = self._handler()
        h._renumber_channel("run1", {"channel_key": "A", "number": 55})
        self.assertEqual(sent[-1][0], 200, sent[-1])
        prefs = lineups_mod.preferences(self.root, "my-lineup")
        self.assertEqual(prefs.get("A", {}).get("number"), 55,
                         "the number was not promoted to the lineup, so a "
                         "fresh run would lose it again")


class TestMediaDurationUsesConfiguredTimeout(unittest.TestCase):
    """Real bug found on a full-codebase review: _media_duration() used a
    bare 15s literal timeout while every other ffprobe/ffmpeg call in
    probe.py derives its timeout from ProbeOptions -- so raising
    capture_timeout (Diagnose mode's longer sample) had no effect on
    measuring that same capture's duration afterward, which could then
    itself time out on a slow host and silently zero measured_kbps.
    """

    def test_probe_timeout_is_passed_to_the_duration_probe(self):
        from probarr.probe import _media_duration, ProbeOptions
        seen = {}
        def fake_run(cmd, timeout):
            seen["timeout"] = timeout
            class R:
                returncode = 0
                stdout = b"12.5"
            return R(), False
        opts = ProbeOptions(probe_timeout=99)
        with unittest.mock.patch("probarr.probe._run", fake_run):
            dur = _media_duration("/tmp/x.ts", opts)
        self.assertEqual(seen["timeout"], 99)
        self.assertEqual(dur, 12.5)


class TestRankPickExcludesPlaceholders(unittest.TestCase):
    """Real bug found on a full-codebase review: pick()'s usable-candidates
    filter included STATUS_PLACEHOLDER alongside ok/dirty, directly
    contradicting this module's own _STATUS_RANK comment ("Dead, frameless
    and placeholder streams are unusable and stay at the bottom"). Dead
    code today (no caller anywhere in probarr/ or tests/), but a latent
    trap for whoever wires it up next, given it looks like the ranking
    module's obvious public entry point.
    """

    def test_a_placeholder_candidate_is_never_returned_as_usable(self):
        from probarr.rank import pick
        results = [
            {"rec_key": "a", "status": "placeholder", "width": 1920,
            "height": 1080, "corruption_errors": 0},
            {"rec_key": "b", "status": "dead"},
        ]
        self.assertEqual(pick(results), [])


class TestAtomicWriteHelperCoversEveryWriter(Temp):
    """Real cleanup finding from a full-codebase review: only the wantlist
    writer had grown fsync() + on-failure temp-file cleanup (after a real
    data-loss incident), while write_meta/write_removals/write_excluded/
    write_selection/write_push_status still had the plain tmp+os.replace
    version -- the same class of bug the wantlist writer was hardened
    against was still fully reachable through any of the other five.
    Consolidated into one _atomic_write_json() helper; this proves each
    caller actually goes through it (crash mid-write leaves no .tmp
    litter and the previous file survives untouched).
    """

    def _assert_write_is_atomic(self, store, write_fn, path, prior_content):
        with open(path, "w", encoding="utf-8") as f:
            f.write(prior_content)
        with unittest.mock.patch.object(
                json, "dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                write_fn()
        # The previous file must survive untouched, and no .tmp litter.
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), prior_content)
        self.assertFalse(os.path.exists(path + ".tmp"))

    def test_write_meta_is_atomic(self):
        store = RunStore(self.root, "run1", create=True)
        store.write_meta({"a": 1})
        self._assert_write_is_atomic(
            store, lambda: store.write_meta({"a": 2}), store.meta_path,
            open(store.meta_path, encoding="utf-8").read())

    def test_write_removals_is_atomic(self):
        store = RunStore(self.root, "run1", create=True)
        store.write_removals([{"key": "A"}])
        self._assert_write_is_atomic(
            store, lambda: store.write_removals([{"key": "B"}]),
            store.removals_path, open(store.removals_path, encoding="utf-8").read())

    def test_write_excluded_is_atomic(self):
        store = RunStore(self.root, "run1", create=True)
        store.write_excluded([{"key": "A"}])
        self._assert_write_is_atomic(
            store, lambda: store.write_excluded([{"key": "B"}]),
            store.excluded_path, open(store.excluded_path, encoding="utf-8").read())

    def test_write_selection_is_atomic(self):
        store = RunStore(self.root, "run1", create=True)
        store.write_selection({"A": {"group": "1"}})
        self._assert_write_is_atomic(
            store, lambda: store.write_selection({"A": {"group": "2"}}),
            store.selection_path, open(store.selection_path, encoding="utf-8").read())

    def test_write_push_status_is_atomic(self):
        store = RunStore(self.root, "run1", create=True)
        store.write_push_status({"state": "done"})
        self._assert_write_is_atomic(
            store, lambda: store.write_push_status({"state": "running"}),
            store.push_status_path, open(store.push_status_path, encoding="utf-8").read())


class TestWizardRoute(Temp):
    """/wizard: manually-launched setup wizard, never auto-triggered."""

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="text/html; charset=utf-8", code=200: (
            sent.append((code, body)), sent)[-1]
        return h, sent

    def test_serves_the_wizard_page(self):
        h, sent = self._handler()
        h.path = "/wizard"
        h.do_GET()
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        self.assertIn("Add your provider", body)
        self.assertIn("Connect Dispatcharr", body)

    def test_nav_links_to_it(self):
        from probarr.theme import _NAV_SETUP
        self.assertIn(("wizard", "/wizard", "Setup wizard"), _NAV_SETUP)


class TestPageTemplates(unittest.TestCase):
    """The bug class that broke the Curate page twice: JavaScript written
    inside a Python string, with escapes the interpreter silently ate."""

    def _pages(self):
        from probarr import web as web_mod
        from probarr import wizard as wizard_mod
        return {"curate": curate.HTML, "runs_index": web_mod.INDEX,
                "wizard": wizard_mod.WIZARD_PAGE,
                **{n: getattr(pages, n) for n in
                   ("WANTLIST_PAGE", "SETTINGS_PAGE", "PROVIDERS_PAGE",
                    "NEWRUN_PAGE", "BROWSE_PAGE", "LINEUPS_PAGE")}}

    def test_templates_are_raw_strings(self):
        # web.py's INDEX (the runs list) was missed here for a long time --
        # not raw, and it shipped a genuinely broken confirm() dialog as a
        # result (a single backslash before an embedded quote got eaten by
        # Python instead of reaching the browser, throwing a JS SyntaxError
        # that silently killed the whole script tag -- including the
        # unrelated Delete button's listener in the same block). Scanning
        # web.py here too is what would have caught it before it shipped.
        for path in ("probarr/curate.py", "probarr/pages.py", "probarr/web.py",
                    "probarr/wizard.py"):
            # KNM fix (probarr-vyx): explicit encoding, not the platform
            # default -- on Windows that's cp1252, and web.py contains a
            # byte that isn't valid cp1252, erroring the test outright.
            with open(os.path.join(os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))), path),
                    encoding="utf-8") as f:
                src = f.read()
            for m in re.finditer(r'^([A-Z_]+) = (r?)"""<!doctype', src, re.M):
                self.assertEqual(m.group(2), "r",
                                 f"{m.group(1)} must be a raw string: Python "
                                 "eats the JavaScript's escapes otherwise")

    def test_no_double_escaped_unicode_reaches_the_browser(self):
        # r"\\u2014" would render as a literal backslash-u in the page.
        for name, html in self._pages().items():
            self.assertNotIn(r"\\u", html, f"{name} has a doubled escape")

    def test_every_placeholder_is_substituted_when_rendered(self):
        from probarr import wizard as wizard_mod
        rendered = [pages.wantlist_page(), pages.settings_page(),
                    pages.providers_page(), pages.new_run_page(),
                    pages.browse_page(), pages.lineups_page(),
                    wizard_mod.wizard_page()]
        for html in rendered:
            leftover = re.findall(r"__[A-Z]+__", html)
            self.assertEqual(leftover, [], f"unsubstituted: {leftover}")

    def test_scripts_are_balanced(self):
        for name, html in self._pages().items():
            self.assertEqual(html.count("<script>"), html.count("</script>"),
                             f"{name} has an unbalanced script tag")


class TestIndexRedirect(Temp):
    """"/" is a landing pad, not a page of its own -- it should drop you
    straight into whatever you were last working on (Curate for the newest
    run) rather than an intermediate list you have to click through every
    time. The list itself moved to /runs, still reachable from the Runs
    nav tab, for the times you actually want to browse or delete a run.
    """

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h.send_response = lambda code: sent.append(["status", code])
        h.send_header = lambda k, v: sent.append([k, v])
        h.end_headers = lambda: None
        return h, sent

    def test_redirects_to_the_newest_runs_curate_page(self):
        from probarr.store import RunStore
        RunStore(self.root, "20260101-000000").write_meta({})
        RunStore(self.root, "20260825-000000").write_meta({})
        h, sent = self._handler()
        h.path = "/"
        h.do_GET()
        status = next(v for k, v in sent if k == "status")
        location = next(v for k, v in sent if k == "Location")
        self.assertEqual(status, 302)
        self.assertEqual(location, "/run/20260825-000000/curate")

    def test_with_no_runs_at_all_redirects_to_the_runs_list(self):
        h, sent = self._handler()
        h.path = "/"
        h.do_GET()
        status = next(v for k, v in sent if k == "status")
        location = next(v for k, v in sent if k == "Location")
        self.assertEqual(status, 302)
        self.assertEqual(location, "/runs")


class TestLogos(Temp):
    """logos.py never touches image bytes -- only two small JSON listings
    (country names, per-country filenames) ever get cached. These tests
    mock the network entirely and check the caching and matching logic in
    isolation from GitHub's actual API.
    """

    def test_search_prefers_the_closer_normalized_match(self):
        from probarr import logos as logos_mod
        from probarr.normalize import Normalizer
        with unittest.mock.patch.object(
                logos_mod, "fetch_country_logos",
                return_value=["bbc-one-uk.png", "bbc-news-uk.png",
                              "itv1-uk.png"]):
            results = logos_mod.search(self.root, "UK: BBC One HD",
                                       "united-kingdom", Normalizer())
        self.assertTrue(results)
        self.assertEqual(results[0]["filename"], "bbc-one-uk.png")
        self.assertTrue(results[0]["url"].startswith(
            "https://raw.githubusercontent.com/tv-logo/tv-logos/main/"
            "countries/united-kingdom/"))

    def test_search_with_no_country_or_query_returns_nothing_and_fetches_nothing(self):
        from probarr import logos as logos_mod
        from probarr.normalize import Normalizer
        with unittest.mock.patch.object(
                logos_mod, "fetch_country_logos") as fake_fetch:
            self.assertEqual(logos_mod.search(self.root, "bbc one", "",
                                              Normalizer()), [])
            self.assertEqual(logos_mod.search(self.root, "", "united-kingdom",
                                              Normalizer()), [])
            fake_fetch.assert_not_called()

    def test_fetch_country_logos_is_cached_to_disk_not_refetched(self):
        from probarr import logos as logos_mod
        logos_mod._mem.clear()
        calls = []

        def fake_get_json(url):
            calls.append(url)
            return [{"name": "bbc-one-uk.png", "type": "file"},
                   {"name": "README.md", "type": "file"}]

        with unittest.mock.patch.object(logos_mod, "_get_json", fake_get_json):
            first = logos_mod.fetch_country_logos(self.root, "united-kingdom")
            logos_mod._mem.clear()  # force the disk tier, not the in-memory one
            second = logos_mod.fetch_country_logos(self.root, "united-kingdom")
        self.assertEqual(first, ["bbc-one-uk.png"])
        self.assertEqual(second, first)
        self.assertEqual(len(calls), 1, "second call should have hit the disk cache")

    def test_a_failed_fetch_yields_an_empty_list_not_an_exception(self):
        from probarr import logos as logos_mod
        logos_mod._mem.clear()
        with unittest.mock.patch.object(
                logos_mod, "_get_json", side_effect=OSError("network down")):
            self.assertEqual(logos_mod.fetch_countries(self.root), [])
            self.assertEqual(
                logos_mod.fetch_country_logos(self.root, "united-kingdom"), [])

    def test_resolve_curated_prefers_an_explicit_logo_override(self):
        from probarr import web as web_mod
        from probarr.store import RunStore
        store = RunStore(self.root, "run1")
        store.append({"rec_key": "BBCONE|s1", "channel_key": "BBCONE",
                      "stream_id": "s1", "stream_name": "BBC One",
                      "status": "ok", "url": "http://x/1", "url_redacted": "",
                      "group": "", "logo": "https://example.com/m3u-logo.png",
                      "tvg_id": "", "probed_at": 1})
        store.write_wantlist_raw(
            [{"key": "BBCONE", "number": "101", "name": "BBC One"}], [])
        store.write_selection({"BBCONE": {
            "logo_override": "https://raw.githubusercontent.com/tv-logo/"
                             "tv-logos/main/countries/united-kingdom/"
                             "bbc-one-uk.png"}})
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        curated = h._resolve_curated(store)
        ch = next(c for c in curated if c["key"] == "BBCONE")
        self.assertEqual(ch["logo_url"],
                         "https://raw.githubusercontent.com/tv-logo/tv-logos/"
                         "main/countries/united-kingdom/bbc-one-uk.png")


class TestRunIdIsNotAPath(Temp):
    """Reported by a reviewer on Discord, and confirmed by exercising it
    against a live instance: RunStore's constructor built a directory path
    straight from a URL-supplied run id and os.makedirs'd four
    subdirectories under it, with no validation at all. A single
    unauthenticated GET to /run/<anything>/thumbs/x.jpg therefore created
    directories on disk -- unbounded, so a crawler or a script could
    exhaust inodes. RunStore.delete() already validated its run id with
    realpath for exactly this reason; the constructor never did.
    """

    def test_a_traversing_run_id_cannot_escape_the_root(self):
        from probarr.store import RunStore
        for evil in ("../escape", "..", ".", "a/b", "..\\escape", "/etc"):
            with self.assertRaises(ValueError, msg=f"accepted {evil!r}"):
                RunStore(self.root, evil)

    def test_an_unknown_run_id_creates_nothing_on_disk(self):
        from probarr.store import RunStore
        before = sorted(os.listdir(self.root))
        RunStore(self.root, "never-seen-before")
        self.assertEqual(sorted(os.listdir(self.root)), before,
                         "reading an unknown run must not create directories")

    def test_an_existing_run_still_gets_its_subdirectories(self):
        from probarr.store import RunStore
        RunStore(self.root, "real-run", create=True)
        again = RunStore(self.root, "real-run")
        self.assertTrue(os.path.isdir(again.thumbs))
        self.assertTrue(os.path.isdir(again.clips))

    def test_a_brand_new_run_with_no_id_still_creates_its_own_home(self):
        from probarr.store import RunStore
        s = RunStore(self.root)
        self.assertTrue(os.path.isdir(s.frames))

    def test_a_rejected_run_id_answers_400_rather_than_dropping_the_request(self):
        # Confirmed live: raising out of the handler dropped the connection
        # outright (curl reported HTTP 000), which is a worse failure than
        # the directory creation the validation exists to prevent.
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="text/plain", code=200: sent.append(code)
        h.path = "/run/.hidden/thumbs/x.jpg"
        h.do_GET()
        self.assertEqual(sent, [400])


class TestCatalogCacheIsNotPickle(Temp):
    """The provider-catalogue disk cache used pickle.load(), which is
    arbitrary code execution for anyone able to write into the config
    directory. Stream is a plain dataclass, so JSON carries it losslessly
    with none of that exposure.
    """

    def test_round_trips_streams_through_the_disk_cache(self):
        from probarr import web as web_mod
        from probarr.sources.base import Stream
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        made = [Stream(id="m3u:abc", name="BBC One", url="http://x/1",
                       group="UK", logo="http://l/1.png", tvg_id="bbc1",
                       source="m3u", attrs={"k": "v"})]
        with unittest.mock.patch.object(web_mod, "load_source",
                                        return_value=made) as fake:
            first = h._load_source_cached("m3u://fake")
            second = h._load_source_cached("m3u://fake")   # served from disk
            self.assertEqual(fake.call_count, 1)
        self.assertEqual([s.name for s in second], ["BBC One"])
        self.assertEqual(second[0].attrs, {"k": "v"})
        self.assertEqual(second[0].url, "http://x/1")
        self.assertIsInstance(second[0], Stream)

    def test_the_cache_file_is_json_not_pickle(self):
        from probarr import web as web_mod
        from probarr.sources.base import Stream
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        with unittest.mock.patch.object(
                web_mod, "load_source",
                return_value=[Stream(id="i", name="n", url="u")]):
            h._load_source_cached("m3u://fake")
        path = h._catalog_disk_path("m3u://fake")
        with open(path, encoding="utf-8") as f:
            json.load(f)          # raises if this is a pickle


class TestDroppedChannelsAreReported(Temp):
    """Reported by a reviewer on Discord. A channel the provider has
    stopped carrying is visible in Curate (it lands as `missing`), but the
    EXPORT path skipped it with a bare `continue` -- so it appeared nowhere
    in the push preview, and Dispatcharr silently kept serving the old
    channel pointing at a now-dead stream. Never deleting is deliberate
    (see dispatcharr_export.py); giving no signal at all was not.
    """

    def _run_with_a_dropped_channel(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        # BBCONE probed fine; BBCTWO is wanted but the provider carries
        # nothing for it any more, so it has no results at all.
        store.append({"rec_key": "BBCONE|s1", "channel_key": "BBCONE",
                      "stream_id": "s1", "stream_name": "BBC One",
                      "status": "ok", "url": "http://x/1", "url_redacted": "",
                      "group": "", "logo": "", "tvg_id": "", "probed_at": 1})
        store.write_wantlist_raw(
            [{"key": "BBCONE", "number": 101, "name": "BBC One"},
             {"key": "BBCTWO", "number": 102, "name": "BBC Two"}], [])
        return store

    def test_a_channel_with_no_candidates_is_reported_not_silently_skipped(self):
        from probarr import web as web_mod
        store = self._run_with_a_dropped_channel()
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        curated, dropped = h._resolve_curated(store, report_dropped=True)
        self.assertEqual([c["key"] for c in curated], ["BBCONE"])
        self.assertEqual([d["key"] for d in dropped], ["BBCTWO"])
        self.assertEqual(dropped[0]["number"], 102)
        self.assertEqual(dropped[0]["name"], "BBC Two")

    def test_resolve_curated_still_returns_a_plain_list_by_default(self):
        from probarr import web as web_mod
        store = self._run_with_a_dropped_channel()
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        curated = h._resolve_curated(store)
        self.assertEqual([c["key"] for c in curated], ["BBCONE"])

    def test_an_excluded_channel_is_not_reported_as_dropped(self):
        from probarr import web as web_mod
        store = self._run_with_a_dropped_channel()
        # Deliberately excluded is a decision, not a provider failure.
        store.write_selection({"BBCTWO": {"include": False}})
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        _, dropped = h._resolve_curated(store, report_dropped=True)
        self.assertEqual(dropped, [])


class TestGuideParsePeakMemory(Temp):
    """Reported by a reviewer on Discord as "memory usage is high when
    importing EPG during curation" -- correct, and the code comment above
    the parse loop actively claimed the opposite ("peak memory stays flat
    regardless of file size").

    stdlib ElementTree's elem.clear() empties an element but leaves it
    attached to the root, so the root accumulates one empty element per
    channel AND per programme in the whole file -- including every
    programme outside the retention window that gets discarded anyway.
    Measured on a synthetic 63MB guide before the fix: 104MB peak to
    retain 9MB of useful data. Detaching consumed elements from the root
    took the same parse to 0.3MB.
    """

    def _guide_file(self, channels, programmes_each):
        import datetime
        path = os.path.join(self.root, "big.xml")
        base = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)
        with open(path, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0"?><tv>')
            for c in range(channels):
                f.write(f'<channel id="c{c}"><display-name>Chan {c}</display-name></channel>')
            for c in range(channels):
                for p in range(programmes_each):
                    s = (base + datetime.timedelta(hours=p)).strftime("%Y%m%d%H%M%S +0000")
                    e = (base + datetime.timedelta(hours=p + 1)).strftime("%Y%m%d%H%M%S +0000")
                    f.write(f'<programme channel="c{c}" start="{s}" stop="{e}">'
                           f'<title>Prog {p}</title><desc>{"x" * 200}</desc></programme>')
            f.write('</tv>')
        return path

    def test_peak_memory_does_not_scale_with_the_discarded_bulk(self):
        import tracemalloc
        from probarr.epg import Guide
        path = self._guide_file(channels=200, programmes_each=150)
        on_disk = os.path.getsize(path)
        tracemalloc.start()
        g = Guide.load(path, window_hours=6)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertEqual(len(g.display_names), 200)
        # The whole point: the parser must not hold the file. Before the fix
        # peak ran to ~1.6x the file size; a third of it is a wide margin
        # that still fails loudly on any regression to accumulate-the-root.
        self.assertLess(peak, on_disk / 3,
                        f"peak {peak/1e6:.1f}MB parsing a {on_disk/1e6:.1f}MB "
                        "guide -- consumed elements are being retained again")

    def test_the_programmes_actually_in_the_window_still_load(self):
        import datetime
        from probarr.epg import Guide
        at = datetime.datetime.now(datetime.timezone.utc)
        path = self._guide_file(channels=3, programmes_each=8)
        g = Guide.load(path, window_hours=48, at=at - datetime.timedelta(days=3))
        self.assertEqual(len(g.display_names), 3)
        self.assertTrue(sum(len(v) for v in g.programmes.values()) > 0)
        self.assertEqual(g.display_names["c1"], ["Chan 1"])


class TestWantlistWriteIsAtomic(Temp):
    """The wantlist is where a channel's NUMBER and NAME live, and
    _resolve_curated() skips any channel with no number from every export.
    A half-written wantlist therefore does not fail loudly -- it silently
    drops channels from the M3U and from the Dispatcharr push, which is the
    same silent-wrong-answer shape as the other bugs found in review.

    Every other write in the project already goes through a temp file and
    os.replace (21 call sites); these two were the exception.
    """

    def _crashing_dump(self, real):
        calls = {"n": 0}

        def dump(obj, f, **kw):
            calls["n"] += 1
            f.write('{"wanted": [{"key": "PARTIAL"')   # plausible, truncated
            raise OSError("disk full")
        return dump

    def test_a_failed_write_leaves_the_previous_wantlist_intact(self):
        import json as _json
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw(
            [{"key": "BBCONE", "number": 101, "name": "BBC One"}], [])
        good = store.read_wantlist()
        self.assertEqual(good["wanted"][0]["key"], "BBCONE")

        with unittest.mock.patch.object(
                _json, "dump", self._crashing_dump(_json.dump)):
            with self.assertRaises(OSError):
                store.write_wantlist_raw(
                    [{"key": "BBCTWO", "number": 102, "name": "BBC Two"}], [])

        # The old wantlist must still be readable and complete -- not
        # truncated, not empty, not half of the new one.
        after = store.read_wantlist()
        self.assertEqual(after, good,
                         "a crashed write corrupted the previous wantlist")

    def test_a_successful_write_still_replaces_it(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw([{"key": "A", "number": 1, "name": "A"}], [])
        store.write_wantlist_raw([{"key": "B", "number": 2, "name": "B"}], [])
        self.assertEqual([w["key"] for w in store.read_wantlist()["wanted"]], ["B"])

    def test_no_temp_file_is_left_behind(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw([{"key": "A", "number": 1, "name": "A"}], [])
        leftovers = [f for f in os.listdir(store.dir) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])


class TestSavedWantlistNamesAreCaseInsensitive(Temp):
    """Real-world usability bug found in a fresh-user walkthrough: a saved
    wantlist named "top10-us-paytv" was later re-saved under the
    differently-cased "Top-10-US-Pay-TV" (the page's own display re-render
    of the name), which -- because safe_name() was case-sensitive and the
    filesystem underneath it is too -- created a SECOND file instead of
    updating the first. The wantlists page then showed two lists, both
    claiming to hold the same 10 channels, and the user had to notice and
    manually delete the duplicate.
    """

    def test_saving_under_a_different_case_updates_the_same_file(self):
        from probarr import wantlist as wl
        wl.write_saved(self.root, "top10-us-paytv", "ESPN\n")
        wl.write_saved(self.root, "Top10-Us-Paytv", "ESPN\nTNT\n")
        saved = wl.list_saved(self.root)
        self.assertEqual(len(saved), 1,
                         "re-saving under a different case must update the "
                         "existing list, not create a second one")
        self.assertEqual(wl.read_saved(self.root, "top10-us-paytv"), "ESPN\nTNT\n")

    def test_reading_back_is_also_case_insensitive(self):
        from probarr import wantlist as wl
        wl.write_saved(self.root, "UK-Lineup", "BBC One\n")
        self.assertEqual(wl.read_saved(self.root, "uk-lineup"), "BBC One\n")


class TestCodeReviewFixes(Temp):
    """Regression tests for the nine findings from the high-effort review.
    Several were regressions introduced by earlier fixes in the same batch,
    which is exactly why they get tests rather than just patches.
    """

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="text/plain", code=200: sent.append(
            (code, body))
        return h, sent

    # -- export.m3u crash on a run with no directory ----------------------
    def test_export_m3u_on_an_unknown_run_is_a_404_not_a_crash(self):
        h, sent = self._handler()
        h._export_m3u("ghost-run")          # used to raise FileNotFoundError
        self.assertEqual(sent[0][0], 404)

    def test_export_m3u_creates_nothing_on_disk_for_an_unknown_run(self):
        h, _ = self._handler()
        before = sorted(os.listdir(self.root))
        h._export_m3u("ghost-run")
        self.assertEqual(sorted(os.listdir(self.root)), before)

    # -- only an invalid run id is a 400 ----------------------------------
    def test_corrupt_run_json_is_not_reported_as_a_bad_request(self):
        from probarr import web as web_mod
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_meta({})
        with open(store.meta_path, "w") as f:
            f.write("{truncated")          # a crash mid-write
        h, sent = self._handler()
        h.path = "/run/run1/curate"
        with self.assertRaises(ValueError):
            h.do_GET()                      # propagates as a server fault
        self.assertEqual(sent, [], "a corrupt run.json must not answer 400")

    def test_an_invalid_run_id_is_still_a_400(self):
        h, sent = self._handler()
        h.path = "/run/.hidden/thumbs/x.jpg"
        h.do_GET()
        self.assertEqual(sent[0][0], 400)

    # -- gzip sources must not leak the handle they wrap ------------------
    def test_closing_a_gzipped_guide_closes_the_underlying_file(self):
        import gzip as _gzip
        from probarr import epg as epg_mod
        path = os.path.join(self.root, "guide.xml.gz")
        with _gzip.open(path, "wb") as f:
            f.write(b'<?xml version="1.0"?><tv><channel id="c1">'
                    b'<display-name>X</display-name></channel></tv>')
        stream = epg_mod._open(path)
        inner = stream.fileobj
        stream.close()
        self.assertTrue(inner.closed,
                        "GzipFile.close() leaves its fileobj open unless "
                        "the close is cascaded")

    def test_a_gzipped_guide_still_parses(self):
        import gzip as _gzip
        from probarr.epg import Guide
        path = os.path.join(self.root, "guide.xml.gz")
        with _gzip.open(path, "wb") as f:
            f.write(b'<?xml version="1.0"?><tv><channel id="c1">'
                    b'<display-name>BBC One</display-name></channel></tv>')
        self.assertEqual(Guide.load(path).display_names["c1"], ["BBC One"])

    # -- a pinned EPG source's answer stands, including "nothing on" ------
    def _guide(self, name, channel_name, title=None):
        import datetime as _dt
        xml = os.path.join(self.root, name + ".xml")
        now = _dt.datetime.now(_dt.timezone.utc)
        prog = ""
        if title:
            s = (now - _dt.timedelta(minutes=30)).strftime("%Y%m%d%H%M%S +0000")
            e = (now + _dt.timedelta(minutes=30)).strftime("%Y%m%d%H%M%S +0000")
            prog = (f'<programme channel="c1" start="{s}" stop="{e}">'
                   f'<title>{title}</title></programme>')
        with open(xml, "w", encoding="utf-8") as f:
            f.write(f'<?xml version="1.0"?><tv><channel id="c1">'
                   f'<display-name>{channel_name}</display-name></channel>'
                   f'{prog}</tv>')
        from probarr import epgsources
        # KNM fix (probarr-9wl): pathlib.as_uri(), not string concat --
        # "file://" + xml is malformed on Windows (file://B:\...) and
        # fails in urlopen; as_uri() produces a real file:///B:/... URL.
        epgsources.save(self.root, name, pathlib.Path(xml).as_uri())

    def test_a_pinned_source_with_a_schedule_gap_does_not_fall_through(self):
        from probarr import web as web_mod
        from probarr.store import RunStore
        web_mod.Handler.root = self.root
        # The pinned source carries the channel but has nothing on air.
        self._guide("aaa-other", "National Geographic", "Wrong Programme")
        self._guide("zzz-pinned", "National Geographic", None)
        store = RunStore(self.root, "run1", create=True)
        store.write_selection({"NATGEO": {"epg_source": "zzz-pinned"}})
        got = web_mod.Handler._expected_now(
            {"channel_key": "NATGEO", "stream_name": "National Geographic",
             "tvg_id": ""}, store)
        self.assertIsNone(got, "a gap in the pinned source must not be "
                               "filled from a different source")

    def test_a_pinned_source_that_does_not_carry_the_channel_still_falls_back(self):
        from probarr import web as web_mod
        from probarr.store import RunStore
        web_mod.Handler.root = self.root
        self._guide("aaa-other", "National Geographic", "Real Programme")
        self._guide("zzz-pinned", "Some Other Channel", "Irrelevant")
        store = RunStore(self.root, "run1", create=True)
        store.write_selection({"NATGEO": {"epg_source": "zzz-pinned"}})
        got = web_mod.Handler._expected_now(
            {"channel_key": "NATGEO", "stream_name": "National Geographic",
             "tvg_id": ""}, store)
        self.assertEqual(got["title"], "Real Programme")

    # -- a channel with no number is reported, not silently skipped -------
    def test_a_channel_with_no_number_is_reported_as_dropped(self):
        from probarr import web as web_mod
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.append({"rec_key": "ORPHAN|s1", "channel_key": "ORPHAN",
                      "stream_id": "s1", "stream_name": "Orphan",
                      "status": "ok", "url": "http://x/1", "url_redacted": "",
                      "group": "", "logo": "", "tvg_id": "", "probed_at": 1})
        store.write_wantlist_raw([{"key": "ORPHAN", "name": "Orphan"}], [])
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        curated, dropped = h._resolve_curated(store, report_dropped=True)
        self.assertEqual(curated, [])
        self.assertEqual([d["key"] for d in dropped], ["ORPHAN"])
        self.assertIn("number", dropped[0]["reason"])


class TestLogoCacheDoesNotPoison(Temp):
    """A failed GitHub fetch used to be written to disk as an empty result
    for the full TTL -- seven days for the country list -- so one network
    blip made the logo picker look permanently broken.
    """

    def test_a_failed_fetch_is_not_cached(self):
        from probarr import logos as logos_mod
        logos_mod._mem.clear()
        with unittest.mock.patch.object(
                logos_mod, "_get_json", side_effect=OSError("network down")):
            self.assertEqual(logos_mod.fetch_countries(self.root), [])
        # Nothing persisted, so the very next call tries the network again.
        calls = []

        def ok(url):
            calls.append(url)
            return [{"name": "united-kingdom", "type": "dir"}]
        logos_mod._mem.clear()
        with unittest.mock.patch.object(logos_mod, "_get_json", ok):
            self.assertEqual(logos_mod.fetch_countries(self.root),
                             ["united-kingdom"])
        self.assertEqual(len(calls), 1, "the failure was cached and blocked "
                                        "a later successful fetch")

    def test_a_failure_falls_back_to_a_stale_cached_copy(self):
        from probarr import logos as logos_mod
        logos_mod._mem.clear()
        with unittest.mock.patch.object(
                logos_mod, "_get_json",
                return_value=[{"name": "united-kingdom", "type": "dir"}]):
            logos_mod.fetch_countries(self.root)
        # Age the cache past its TTL, then fail the network.
        import time as _time
        path = logos_mod._disk_path(self.root, "countries")
        old = _time.time() - (logos_mod._COUNTRIES_TTL + 60)
        os.utime(path, (old, old))
        logos_mod._mem.clear()
        with unittest.mock.patch.object(
                logos_mod, "_get_json", side_effect=OSError("network down")):
            self.assertEqual(logos_mod.fetch_countries(self.root),
                             ["united-kingdom"])

    def test_a_genuinely_empty_result_is_still_cached(self):
        from probarr import logos as logos_mod
        logos_mod._mem.clear()
        with unittest.mock.patch.object(logos_mod, "_get_json",
                                        return_value=[]) as fake:
            self.assertEqual(logos_mod.fetch_countries(self.root), [])
            logos_mod._mem.clear()
            self.assertEqual(logos_mod.fetch_countries(self.root), [])
        self.assertEqual(fake.call_count, 1)


class TestGetOrCreateLogoDoesNotRescan(unittest.TestCase):
    """The pre-scan re-answered a question its only caller had already
    answered, at the cost of a full paginated fetch of the Logo table per
    new logo -- fifty curated logos meant fifty redundant full fetches
    against an API that rate-limits.
    """

    def _client(self, existing):
        from probarr.sources.dispatcharr import Dispatcharr
        c = Dispatcharr("http://fake", "u", "p")
        c.calls = []

        def api(method, path, body=None):
            c.calls.append((method, path))
            if method == "POST" and path == "/api/channels/logos/":
                if any(l["url"] == body["url"] for l in existing):
                    raise RuntimeError("400 duplicate url")
                row = {"id": 900 + len(existing), **body}
                existing.append(row)
                return row
            if path.startswith("/api/channels/logos/"):
                return {"results": existing}
            raise AssertionError(path)
        c.api = api
        return c

    def test_a_new_logo_costs_one_call_and_no_listing(self):
        c = self._client([])
        self.assertEqual(c.get_or_create_logo("BBC One", "http://l/1.png"), 900)
        self.assertEqual(c.calls, [("POST", "/api/channels/logos/")])

    def test_a_duplicate_still_resolves_to_the_existing_row(self):
        c = self._client([{"id": 5, "name": "BBC One", "url": "http://l/1.png"}])
        self.assertEqual(c.get_or_create_logo("BBC One", "http://l/1.png"), 5)


class TestEpgMemory(unittest.TestCase):
    """probarr-6qy: a large XMLTV feed should not blow up memory.

    _open() must stream the source into iterparse rather than reading the
    whole payload into a bytes object first, and Guide.load()'s iterparse
    loop must not let the tree root accumulate an ever-growing list of
    emptied child stubs -- elem.clear() alone does not do that.
    """

    def _write_xmltv(self, path, n_channels=50, n_programmes=500):
        with open(path, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<tv>\n')
            for i in range(n_channels):
                f.write(f'<channel id="ch{i}"><display-name>Ch {i}'
                        f'</display-name></channel>\n')
            at = datetime.datetime.now(datetime.timezone.utc)
            for i in range(n_programmes):
                start = at + datetime.timedelta(minutes=i)
                stop = start + datetime.timedelta(minutes=1)
                cid = f"ch{i % n_channels}"
                f.write(
                    f'<programme start="{start.strftime("%Y%m%d%H%M%S +0000")}" '
                    f'stop="{stop.strftime("%Y%m%d%H%M%S +0000")}" channel="{cid}">'
                    f'<title>Show {i}</title></programme>\n')
            f.write("</tv>\n")

    def test_open_does_not_buffer_whole_file_before_parsing(self):
        # A local file source should stream from disk, not front-load the
        # entire contents into a single in-memory bytes/BytesIO copy sized
        # to the file. We check this via the object _open() hands back:
        # it must not be a BytesIO holding the full raw bytes.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "guide.xml")
            self._write_xmltv(path)
            size_on_disk = os.path.getsize(path)
            stream = epg._open(path)
            try:
                self.assertNotIsInstance(
                    stream, io.BytesIO,
                    "_open() should stream from disk, not buffer the full "
                    "file into a BytesIO before iterparse ever starts")
            finally:
                stream.close()
            self.assertGreater(size_on_disk, 0)

    def test_load_does_not_retain_ancestor_stubs_for_every_element(self):
        # elem.clear() only empties the current element -- it does not
        # detach it from its parent. Guide.load() must actively drop
        # processed children from the tree root (or otherwise avoid
        # accumulating one stub per channel/programme ever seen), or peak
        # memory grows without bound on a large aggregated feed. We patch
        # ET.iterparse to snoop on the root's child count as Guide.load()
        # runs its real loop.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "guide.xml")
            self._write_xmltv(path, n_channels=20, n_programmes=2000)

            real_iterparse = ET.iterparse
            max_root_children = []

            def spying_iterparse(source, events=()):
                root = []
                for event, elem in real_iterparse(source, events=events):
                    if event == "start" and not root:
                        root.append(elem)
                    if root:
                        max_root_children.append(len(root[0]))
                    yield event, elem

            with unittest.mock.patch.object(epg.ET, "iterparse", spying_iterparse):
                g = epg.Guide.load(path)

            self.assertLess(
                max(max_root_children), 2020,
                "Guide.load() leaves an empty stub on the tree root for "
                "every channel/programme element it has ever consumed -- "
                "elem.clear() alone doesn't detach it from its parent")
            self.assertGreater(len(g.programmes), 0)


class TestStrictRegionFiltersUnmarkedChannels(unittest.TestCase):
    """probarr-oz2: the Regions box on the New Run page never actually
    restricted anything, because the web UI had no way to set
    strict_region and group_candidates() defaults to including unmarked
    candidates. A channel with no recognisable country marker in its name
    OR group title sails through a Regions filter untouched -- exactly
    what "no matter what is entered, US, USA... it still imports from
    other countries" describes on an aggregated multi-country provider,
    since plenty of its channels carry no marker at all.
    """

    def _streams(self):
        from probarr.sources.base import Stream
        return [
            Stream(id="1", name="US: CNN", url="http://x/1"),
            Stream(id="2", name="UK: CNN", url="http://x/2"),
            Stream(id="3", name="CNN", url="http://x/3"),   # no marker at all
        ]

    def test_unmarked_channel_passes_a_region_filter_by_default(self):
        from probarr.normalize import Normalizer, group_candidates
        pools = group_candidates(self._streams(), Normalizer(), regions=["US"])
        ids = {s.id for pool in pools.values() for s in pool}
        self.assertIn("1", ids, "the US-marked channel must pass")
        self.assertNotIn("2", ids, "the UK-marked channel must be rejected")
        self.assertIn("3", ids,
                      "current (surprising) default: an unmarked channel "
                      "passes a Regions filter it was never shown to match")

    def test_strict_mode_drops_the_unmarked_channel_too(self):
        from probarr.normalize import Normalizer, group_candidates
        pools = group_candidates(self._streams(), Normalizer(), regions=["US"],
                                 include_unmarked=False)
        ids = {s.id for pool in pools.values() for s in pool}
        self.assertEqual(ids, {"1"},
                         "strict mode must keep only the positively-US-marked "
                         "channel")


class TestRegionFilterTreatsUsAndUsaAsTheSameCountry(unittest.TestCase):
    """Real-world usability bug found in a fresh-user walkthrough: a source
    naming its US channels "USA: ESPN" (not "US: ESPN") was silently
    invisible under a Regions=US filter, and a Regions=USA filter equally
    missed "US:"-prefixed channels -- because DEFAULT_REGION_TAGS treats
    "US" and "USA" as two unrelated tags. Same real country, same provider,
    same intent typing either spelling; group_candidates() must not care
    which one the operator typed vs which one a given stream happens to use.
    """

    def _streams(self):
        from probarr.sources.base import Stream
        return [
            Stream(id="1", name="US: ESPN", url="http://x/1"),
            Stream(id="2", name="USA: ESPN", url="http://x/2"),
            Stream(id="3", name="UK: ESPN", url="http://x/3"),
        ]

    def test_a_us_filter_also_matches_usa_marked_channels(self):
        from probarr.normalize import Normalizer, group_candidates
        pools = group_candidates(self._streams(), Normalizer(), regions=["US"],
                                 include_unmarked=False)
        ids = {s.id for pool in pools.values() for s in pool}
        self.assertEqual(ids, {"1", "2"})

    def test_a_usa_filter_also_matches_us_marked_channels(self):
        from probarr.normalize import Normalizer, group_candidates
        pools = group_candidates(self._streams(), Normalizer(), regions=["USA"],
                                 include_unmarked=False)
        ids = {s.id for pool in pools.values() for s in pool}
        self.assertEqual(ids, {"1", "2"})


class TestRunKwargsWiresStrictRegion(Temp):
    """The fix: _run_kwargs() (the browser New Run form's path into
    runner.start_run) must actually read strict_region from the request
    body -- previously nothing in web.py referenced it at all, so no
    request from the UI could ever reach group_candidates() with
    include_unmarked=False, no matter what the user typed into Regions.
    """

    def test_strict_region_true_is_passed_through(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        kwargs = h._run_kwargs({"source": "http://x/playlist.m3u",
                                "regions": "US", "strict_region": True})
        self.assertTrue(kwargs["strict_region"])

    def test_strict_region_defaults_to_false(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        kwargs = h._run_kwargs({"source": "http://x/playlist.m3u",
                                "regions": "US"})
        self.assertFalse(kwargs["strict_region"])


class TestTagSettings(Temp):
    """A durable, user-editable list of region/quality tags -- previously
    the only way to add a provider's own non-standard prefix was the
    New Run form's one-off "Custom prefixes" field, retyped every run and
    never remembered. See tagsettings.py's own module docstring."""

    def test_uncustomised_category_tracks_the_live_code_constant(self):
        from probarr import tagsettings
        from probarr.normalize import DEFAULT_REGION_TAGS
        self.assertEqual(tagsettings.tags(self.root, "region"),
                         list(DEFAULT_REGION_TAGS))
        self.assertFalse(tagsettings.is_customised(self.root, "region"))

    def test_add_then_read_round_trips(self):
        from probarr import tagsettings
        tagsettings.add(self.root, "region", "od")
        self.assertIn("OD", tagsettings.tags(self.root, "region"))
        self.assertTrue(tagsettings.is_customised(self.root, "region"))

    def test_add_is_idempotent(self):
        from probarr import tagsettings
        tagsettings.add(self.root, "region", "OD")
        tagsettings.add(self.root, "region", "OD")
        self.assertEqual(tagsettings.tags(self.root, "region").count("OD"), 1)

    def test_remove_only_touches_the_named_tag(self):
        from probarr import tagsettings
        from probarr.normalize import DEFAULT_REGION_TAGS
        tagsettings.remove(self.root, "region", "NL")
        tags = tagsettings.tags(self.root, "region")
        self.assertNotIn("NL", tags)
        self.assertIn("UK", tags)
        self.assertEqual(len(tags), len(DEFAULT_REGION_TAGS) - 1)

    def test_restore_defaults_undoes_customisation(self):
        from probarr import tagsettings
        from probarr.normalize import DEFAULT_REGION_TAGS
        tagsettings.add(self.root, "region", "OD")
        tagsettings.restore_defaults(self.root, "region")
        self.assertEqual(tagsettings.tags(self.root, "region"),
                         list(DEFAULT_REGION_TAGS))
        self.assertFalse(tagsettings.is_customised(self.root, "region"))

    def test_restoring_region_does_not_touch_quality(self):
        from probarr import tagsettings
        tagsettings.add(self.root, "region", "OD")
        tagsettings.add(self.root, "quality", "GOLD")
        tagsettings.restore_defaults(self.root, "region")
        self.assertIn("GOLD", tagsettings.tags(self.root, "quality"))
        self.assertTrue(tagsettings.is_customised(self.root, "quality"))

    def test_rejects_an_unknown_category(self):
        from probarr import tagsettings
        with self.assertRaises(ValueError):
            tagsettings.tags(self.root, "bogus")

    def test_rejects_a_blank_tag(self):
        from probarr import tagsettings
        with self.assertRaises(ValueError):
            tagsettings.add(self.root, "region", "   ")


class TestDeleteReasons(Temp):
    """A durable, user-editable list of preset reasons for Curate's Delete
    stream dialog -- see reasons.py's own module docstring."""

    def test_uncustomised_tracks_the_built_in_defaults(self):
        from probarr import reasons
        self.assertEqual(reasons.list_all(self.root), reasons.DEFAULT_REASONS)
        self.assertFalse(reasons.is_customised(self.root))

    def test_add_then_read_round_trips_and_keeps_casing(self):
        from probarr import reasons
        reasons.add(self.root, "Buffers constantly")
        self.assertIn("Buffers constantly", reasons.list_all(self.root))
        self.assertTrue(reasons.is_customised(self.root))

    def test_add_is_idempotent(self):
        from probarr import reasons
        reasons.add(self.root, "Buffers constantly")
        reasons.add(self.root, "Buffers constantly")
        self.assertEqual(reasons.list_all(self.root).count("Buffers constantly"), 1)

    def test_remove_only_touches_the_named_reason(self):
        from probarr import reasons
        reasons.remove(self.root, "Wrong channel")
        current = reasons.list_all(self.root)
        self.assertNotIn("Wrong channel", current)
        self.assertIn("Wrong aspect ratio", current)

    def test_restore_defaults_undoes_customisation(self):
        from probarr import reasons
        reasons.add(self.root, "Buffers constantly")
        reasons.restore_defaults(self.root)
        self.assertEqual(reasons.list_all(self.root), reasons.DEFAULT_REASONS)
        self.assertFalse(reasons.is_customised(self.root))

    def test_rejects_a_blank_reason(self):
        from probarr import reasons
        with self.assertRaises(ValueError):
            reasons.add(self.root, "   ")


class TestDiagnosingSnapshot(Temp):
    """/api/diagnosing feeds the topbar's badge -- for every in-flight job
    on the shared probe queue (Diagnose, a plain card re-probe, Preview, a
    freshly-added Find-streams pick, an imported channel's first probe --
    all of it, not just Diagnose) it resolves the stream's human name from
    the run's own already-probed results and reports its queue state and
    whether it's specifically a Diagnose, rather than the bare
    channel-key-only count the badge started with."""

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: (
            sent.append((code, body)), sent)[-1]
        return h, sent

    def test_resolves_stream_name_and_reports_state(self):
        import json, time as time_mod
        import threading
        from probarr.store import RunStore
        from probarr.probequeue import ProbeQueue
        from probarr import web as web_mod

        store = RunStore(self.root, "run1", create=True)
        store.write_meta({})
        store.append({"rec_key": "BBCONE|s1", "channel_key": "BBCONE",
                     "stream_id": "s1", "stream_name": "UK: BBC One HD",
                     "status": "ok"})

        release = threading.Event()
        q = ProbeQueue(lambda payload: release.wait(2) or {"status": "ok"},
                       concurrency=lambda: 1, gap=lambda: 0)
        q.submit("run1|BBCONE|s1", {"run_id": "run1", "rec_key": "BBCONE|s1",
                                    "lane": "mybunny", "diagnose": True})
        web_mod.Handler._pq = q
        try:
            for _ in range(50):
                snap = q.snapshot()
                if snap["keys"].get("run1|BBCONE|s1", {}).get("state") == "running":
                    break
                time_mod.sleep(0.02)
            h, sent = self._handler()
            h._diagnosing_snapshot()
        finally:
            release.set()
            web_mod.Handler._pq = None
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        d = json.loads(body)
        self.assertEqual(len(d["items"]), 1)
        item = d["items"][0]
        self.assertEqual(item["run_id"], "run1")
        self.assertEqual(item["channel_key"], "BBCONE")
        self.assertEqual(item["stream_name"], "UK: BBC One HD")
        self.assertEqual(item["state"], "running")

    def test_a_manual_reprobe_is_included_and_flagged_not_diagnose(self):
        """A plain card ↻ re-probe goes through the exact same queue as
        Diagnose -- it must show up in the badge too (that was the whole
        point raised when this was widened), just flagged diagnose:False
        so the popover can still say which kind of probe it is."""
        import json, threading
        from probarr.store import RunStore
        from probarr.probequeue import ProbeQueue
        from probarr import web as web_mod

        store = RunStore(self.root, "run1", create=True)
        store.write_meta({})
        store.append({"rec_key": "BBCONE|s1", "channel_key": "BBCONE",
                     "stream_id": "s1", "stream_name": "UK: BBC One HD",
                     "status": "ok"})

        release = threading.Event()
        q = ProbeQueue(lambda payload: release.wait(2) or {"status": "ok"},
                       concurrency=lambda: 1, gap=lambda: 0)
        q.submit("run1|BBCONE|s1", {"run_id": "run1", "rec_key": "BBCONE|s1",
                                    "lane": "mybunny"})  # no diagnose flag
        web_mod.Handler._pq = q
        try:
            h, sent = self._handler()
            h._diagnosing_snapshot()
        finally:
            release.set()
            web_mod.Handler._pq = None
        code, body = sent[-1]
        d = json.loads(body)
        self.assertEqual(len(d["items"]), 1)
        self.assertEqual(d["items"][0]["stream_name"], "UK: BBC One HD")
        self.assertFalse(d["items"][0]["diagnose"])


class TestDeleteReasonsApiEndpoint(Temp):

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: (
            sent.append((code, body)), sent)[-1]
        return h, sent

    def test_add_via_endpoint(self):
        import json, io
        h, sent = self._handler()
        h.path = "/api/delete-reasons"
        h.command = "POST"
        h.headers = {"Host": "127.0.0.1", "Referer": "http://127.0.0.1/settings"}
        payload = json.dumps({"action": "add", "reason": "Buffers constantly"}).encode()
        h.headers["Content-Length"] = str(len(payload))
        h.rfile = io.BytesIO(payload)
        h._do_POST()
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        d = json.loads(body)
        self.assertIn("Buffers constantly", d["reasons"])

    def test_get_returns_defaults_and_customised_flag(self):
        import json
        h, sent = self._handler()
        h.path = "/api/delete-reasons"
        h.command = "GET"
        h.headers = {}
        h._do_GET()
        code, body = sent[-1]
        d = json.loads(body)
        self.assertEqual(code, 200, body)
        self.assertFalse(d["customised"])
        self.assertIn("Wrong channel", d["reasons"])


class TestDeletingAStreamRemembersItsReason(Temp):
    """candidate-remove's `reason` isn't just logged against this run's
    excluded-stream note -- a genuinely new one also joins the durable
    preset list, so it's a one-click pick on the NEXT delete too."""

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: (
            sent.append((code, body)), sent)[-1]
        return h, sent

    def test_a_freshly_typed_reason_is_added_to_the_saved_list(self):
        import json, io
        from probarr.store import RunStore
        from probarr import reasons
        store = RunStore(self.root, "run1", create=True)
        store.write_meta({})
        store.append({"rec_key": "BBCONE|s1", "channel_key": "BBCONE",
                     "stream_id": "s1", "stream_name": "BBC One",
                     "status": "ok"})
        h, sent = self._handler()
        h.path = "/api/run/run1/candidate-remove"
        h.command = "POST"
        h.headers = {"Host": "127.0.0.1", "Referer": "http://127.0.0.1/run/run1/curate"}
        payload = json.dumps({"rec_key": "BBCONE|s1",
                             "reason": "Buffers constantly"}).encode()
        h.headers["Content-Length"] = str(len(payload))
        h.rfile = io.BytesIO(payload)
        h._do_POST()
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        self.assertIn("Buffers constantly", reasons.list_all(self.root))

    def test_an_already_known_reason_is_not_duplicated(self):
        import json, io
        from probarr.store import RunStore
        from probarr import reasons
        store = RunStore(self.root, "run1", create=True)
        store.write_meta({})
        store.append({"rec_key": "BBCONE|s1", "channel_key": "BBCONE",
                     "stream_id": "s1", "stream_name": "BBC One",
                     "status": "ok"})
        h, sent = self._handler()
        h.path = "/api/run/run1/candidate-remove"
        h.command = "POST"
        h.headers = {"Host": "127.0.0.1", "Referer": "http://127.0.0.1/run/run1/curate"}
        payload = json.dumps({"rec_key": "BBCONE|s1",
                             "reason": "Wrong channel"}).encode()
        h.headers["Content-Length"] = str(len(payload))
        h.rfile = io.BytesIO(payload)
        h._do_POST()
        self.assertEqual(reasons.list_all(self.root).count("Wrong channel"), 1)


class TestTagsApiEndpoint(Temp):

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="application/json", code=200: (
            sent.append((code, body)), sent)[-1]
        return h, sent

    def test_add_via_endpoint(self):
        import json
        h, sent = self._handler()
        # Route through the real dispatch so the same-origin guard and
        # routing table are exercised, not just the bare method.
        h.path = "/api/tags"
        h.command = "POST"
        h.headers = {"Host": "127.0.0.1", "Referer": "http://127.0.0.1/settings"}
        payload = json.dumps({"kind": "region", "action": "add", "tag": "od"}).encode()
        h.headers["Content-Length"] = str(len(payload))
        import io
        h.rfile = io.BytesIO(payload)
        h._do_POST()
        code, body = sent[-1]
        self.assertEqual(code, 200, body)
        d = json.loads(body)
        self.assertIn("OD", d["tags"])

    def test_unknown_kind_rejected(self):
        import json
        h, sent = self._handler()
        h.path = "/api/tags"
        h.command = "POST"
        h.headers = {"Host": "127.0.0.1", "Referer": "http://127.0.0.1/settings"}
        payload = json.dumps({"kind": "bogus", "action": "add", "tag": "x"}).encode()
        h.headers["Content-Length"] = str(len(payload))
        import io
        h.rfile = io.BytesIO(payload)
        h._do_POST()
        self.assertEqual(sent[-1][0], 400)


class TestRunnerMergesSavedTagsWithRunSpecificOnes(Temp):
    """runner._run() must ADD the run-specific `region_tags` argument to the
    operator's SAVED list, never replace it with just the extras --
    Normalizer(region_tags=...) itself replaces wholesale, which is exactly
    the footgun this merge exists to avoid (see runner.py's own comment)."""

    def test_saved_tags_and_run_specific_ones_are_both_present(self):
        from probarr import tagsettings
        from probarr.store import RunStore
        from probarr import runner as runner_mod
        tagsettings.add(self.root, "region", "OD")
        store = RunStore(self.root, "run1", create=True)

        captured = {}
        orig_normalizer = runner_mod.Normalizer
        def spy(*a, **k):
            captured["region_tags"] = k.get("region_tags")
            n = orig_normalizer(*a, **k)
            return n
        with unittest.mock.patch.object(runner_mod, "Normalizer", spy), \
             unittest.mock.patch.object(runner_mod, "load_source",
                                        return_value=[]):
            try:
                runner_mod._run(store, self.root, "http://x/y.m3u", None, None,
                               None, False, ["ZG"], {}, 1, 0, 5, 240, 90, None,
                               1, None, None, True, lambda *a: None, None, None)
            except RuntimeError:
                pass  # ffmpeg not installed in this test environment --
                      # irrelevant; the Normalizer construction we care
                      # about already happened before this point.
        self.assertIn("OD", captured["region_tags"])
        self.assertIn("ZG", captured["region_tags"])
        self.assertIn("UK", captured["region_tags"])


class TestRunKwargsWiresDispatcharrProxy(Temp):
    """_run_kwargs() must read the "prefer_dispatcharr_proxy" body field
    (New Run's opt-in "Dispatcharr proxy" checkbox) through to
    runner.start_run() unchanged -- default False so every existing
    caller/run keeps behaving exactly as before."""

    def _kwargs(self, body):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        return h._run_kwargs(body)

    def test_true_when_checked(self):
        kwargs = self._kwargs({"source": "dispatcharr://u:p@h:9191",
                               "prefer_dispatcharr_proxy": True})
        self.assertTrue(kwargs["prefer_dispatcharr_proxy"])

    def test_false_by_default(self):
        kwargs = self._kwargs({"source": "dispatcharr://u:p@h:9191"})
        self.assertFalse(kwargs["prefer_dispatcharr_proxy"])


class TestRunKwargsWiresRegionTags(Temp):
    """Real Discord report: a provider's own prefixes ("OD:", "PLAY+:",
    "ZG:", "BE-VIP:") aren't in Normalizer's DEFAULT_REGION_TAGS, so they
    stayed glued to the front of the matching key ("ODNPO1" instead of
    "NPO1") no matter how the packaging-stripping regexes were fixed. The
    web UI had no field for this at all -- only the CLI's --region-tags
    flag could set it. _run_kwargs() now reads a comma-separated
    "region_tags" body field and passes it through as a run-specific
    EXTRA; runner._run() is what actually merges it with the operator's
    saved tag vocabulary (see tagsettings.py and
    TestRunnerMergesSavedTagsWithRunSpecificOnes) -- so _run_kwargs()
    itself only needs to parse the raw field correctly, not merge
    anything (Normalizer itself REPLACES its default list wholesale when
    given one, which is exactly why the merge has to happen somewhere,
    just not here any more).
    """

    def _kwargs(self, body):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        return h._run_kwargs(body)

    def test_field_is_parsed_as_a_comma_separated_list(self):
        kwargs = self._kwargs({"source": "http://x/playlist.m3u",
                               "region_tags": "OD, PLAY+, zg"})
        self.assertEqual(kwargs["region_tags"], ["OD", "PLAY+", "ZG"])

    def test_absent_when_the_field_is_blank(self):
        kwargs = self._kwargs({"source": "http://x/playlist.m3u"})
        self.assertIsNone(kwargs["region_tags"])

    def test_normalizer_then_actually_strips_the_custom_prefix(self):
        """End to end: the exact reported failure, fixed -- using the
        SAME merge runner._run() actually performs (saved list + this
        run's extras), not just the raw field."""
        from probarr import tagsettings
        from probarr.normalize import Normalizer
        kwargs = self._kwargs({"source": "http://x/playlist.m3u",
                               "region_tags": "OD, PLAY+, ZG, BE-VIP"})
        merged = list(dict.fromkeys(
            tagsettings.tags(self.root, "region") + kwargs["region_tags"]))
        n = Normalizer(region_tags=merged)
        base = n.key("NPO 1")
        for name in ["OD: NPO 1 ᴿᴬᵂ", "PLAY+: NPO 1 ᴴᴰ",
                     "ZG: NPO 1 ᴿᴬᵂ", "BE-VIP: NPO 1 ᴿᴬᵂ"]:
            self.assertEqual(n.key(name), base, f"{name!r} did not match")


class TestSettingsPostIsAlsoRedacted(Temp):
    """PR #1 redacted GET /api/settings but not the POST response, so the
    save round-trip still handed the raw credential back -- into the
    response body, into any proxy log on that leg, and into the settings
    field on screen until the next reload. The GET fix is only half of it
    unless both directions agree.
    """

    def _handler(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        sent = []
        h._send = lambda body, ctype="text/plain", code=200: sent.append(body)
        h._json_body = lambda: (
            {"source": "xtream://user:sup3rs3cret@host:8080"}, False)
        h.path = "/api/settings"
        # Same-origin write guard (probarr-tj0) now runs ahead of every
        # settings write; a same-origin Referer is what a real browser save
        # sends, and is what this redaction test needs to get past it.
        h.headers = {"Host": "127.0.0.1", "Referer": "http://127.0.0.1/settings"}
        return h, sent

    def test_the_save_response_does_not_echo_the_raw_credential(self):
        import json as _json
        h, sent = self._handler()
        h.do_POST()
        body = _json.loads(sent[0])
        self.assertNotIn("sup3rs3cret", sent[0])
        self.assertEqual(body["source"], "xtream://***:***@host:8080")

    def test_the_real_credential_is_still_what_gets_stored(self):
        from probarr import settings as settings_mod
        h, _ = self._handler()
        h.do_POST()
        # Redaction is a display concern only -- the stored value must
        # remain usable, or the next run cannot reach the provider.
        self.assertEqual(settings_mod.read(self.root)["source"],
                         "xtream://user:sup3rs3cret@host:8080")

    def test_get_and_post_agree_on_what_they_show(self):
        import json as _json
        h, sent = self._handler()
        h.do_POST()
        post_body = _json.loads(sent[0])
        h2, sent2 = self._handler()
        h2.path = "/api/settings"
        h2.do_GET()
        get_body = _json.loads(sent2[0])
        self.assertEqual(post_body["source"], get_body["source"])


class TestStrictRegionFiltersUnmarkedChannels(unittest.TestCase):
    """probarr-oz2: the Regions box on the New Run page never actually
    restricted anything, because the web UI had no way to set
    strict_region and group_candidates() defaults to including unmarked
    candidates. A channel with no recognisable country marker in its name
    OR group title sails through a Regions filter untouched -- exactly
    what "no matter what is entered, US, USA... it still imports from
    other countries" describes on an aggregated multi-country provider,
    since plenty of its channels carry no marker at all.
    """

    def _streams(self):
        from probarr.sources.base import Stream
        return [
            Stream(id="1", name="US: CNN", url="http://x/1"),
            Stream(id="2", name="UK: CNN", url="http://x/2"),
            Stream(id="3", name="CNN", url="http://x/3"),   # no marker at all
        ]

    def test_unmarked_channel_passes_a_region_filter_by_default(self):
        from probarr.normalize import Normalizer, group_candidates
        pools = group_candidates(self._streams(), Normalizer(), regions=["US"])
        ids = {s.id for pool in pools.values() for s in pool}
        self.assertIn("1", ids, "the US-marked channel must pass")
        self.assertNotIn("2", ids, "the UK-marked channel must be rejected")
        self.assertIn("3", ids,
                      "current (surprising) default: an unmarked channel "
                      "passes a Regions filter it was never shown to match")

    def test_strict_mode_drops_the_unmarked_channel_too(self):
        from probarr.normalize import Normalizer, group_candidates
        pools = group_candidates(self._streams(), Normalizer(), regions=["US"],
                                 include_unmarked=False)
        ids = {s.id for pool in pools.values() for s in pool}
        self.assertEqual(ids, {"1"},
                         "strict mode must keep only the positively-US-marked "
                         "channel")


class TestRunKwargsWiresStrictRegion(Temp):
    """The fix: _run_kwargs() (the browser New Run form's path into
    runner.start_run) must actually read strict_region from the request
    body -- previously nothing in web.py referenced it at all, so no
    request from the UI could ever reach group_candidates() with
    include_unmarked=False, no matter what the user typed into Regions.
    """

    def test_strict_region_true_is_passed_through(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        kwargs = h._run_kwargs({"source": "http://x/playlist.m3u",
                                "regions": "US", "strict_region": True})
        self.assertTrue(kwargs["strict_region"])

    def test_strict_region_defaults_to_false(self):
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        kwargs = h._run_kwargs({"source": "http://x/playlist.m3u",
                                "regions": "US"})
        self.assertFalse(kwargs["strict_region"])


class TestSameOriginGuardCoversEveryWrite(Temp):
    """The guard as merged only checked /api/settings and /api/backup/import
    -- two of ~75 POST branches in _do_POST. The identical threat model
    (no login, any device on the LAN or a stray tab can blind-POST)
    applies to the rest just as much. Confirmed live before broadening:
    a forged-Origin POST to /api/run/<id>/selection was accepted and
    silently overwrote curated state. This locks that in for an
    arbitrary write endpoint, not just the two originally covered.
    """

    def _post(self, path, headers, payload):
        import io
        from probarr import web as web_mod
        web_mod.Handler.root = self.root
        h = web_mod.Handler.__new__(web_mod.Handler)
        h.path = path
        h.command = "POST"
        h.headers = dict(headers)
        body = json.dumps(payload).encode("utf-8")
        h.headers["Content-Length"] = str(len(body))
        h.rfile = io.BytesIO(body)
        sent = []
        h._send = lambda b, ctype="application/json", code=200: sent.append((b, code))
        h._do_POST()
        return sent[0]

    def _seeded_run(self):
        from probarr.store import RunStore
        store = RunStore(self.root, "run1", create=True)
        store.write_wantlist_raw(
            [{"key": "BBCONE", "number": 101, "name": "BBC One"}], [])
        store.append({"rec_key": "BBCONE|s1", "channel_key": "BBCONE",
                      "stream_id": "s1", "status": "ok"})
        return store

    def test_a_forged_origin_cannot_write_a_curated_selection(self):
        from probarr.store import RunStore
        self._seeded_run()
        _, code = self._post(
            "/api/run/run1/selection",
            {"Host": "192.168.1.243:7799", "Origin": "http://evil.example"},  # probarr:allow-secret (test fixture IP, not real)
            {"BBCONE": {"group": "HIJACKED"}})
        self.assertEqual(code, 403)
        from probarr.store import RunStore as RS
        self.assertNotEqual(RS(self.root, "run1").read_selection()
                            .get("BBCONE", {}).get("group"), "HIJACKED")

    def test_a_genuine_same_origin_write_still_reaches_a_run_endpoint(self):
        from probarr.store import RunStore
        self._seeded_run()
        _, code = self._post(
            "/api/run/run1/selection",
            {"Host": "192.168.1.243:7799",  # probarr:allow-secret (test fixture IP, not real)
             "Referer": "http://192.168.1.243:7799/run/run1/curate"},  # probarr:allow-secret (test fixture IP, not real)
            {"BBCONE": {"group": "News"}})
        self.assertEqual(code, 200)
        self.assertEqual(RunStore(self.root, "run1").read_selection()
                         ["BBCONE"]["group"], "News")


class TestDeletingARunReleasesItsClaims(Temp):
    """A channel a run pushed to Dispatcharr must reappear as Unclaimed
    once that run is deleted -- otherwise claims.json (a separate,
    instance-wide file the run's own deletion never touches) keeps it
    marked "ours" forever, even though nothing refers to it any more."""

    def test_unclaim_by_source_only_releases_that_runs_claims(self):
        from probarr import claims as claims_mod
        claims_mod.claim(self.root, 1, "ch1", "Channel 1", source="run:run1")
        claims_mod.claim(self.root, 2, "ch2", "Channel 2", source="run:run2")
        released = claims_mod.unclaim_by_source(self.root, "run:run1")
        self.assertEqual(released, 1)
        remaining = claims_mod.read_all(self.root)
        self.assertNotIn(1, remaining)
        self.assertIn(2, remaining)

    def test_unclaim_by_source_is_a_noop_when_nothing_matches(self):
        from probarr import claims as claims_mod
        claims_mod.claim(self.root, 2, "ch2", "Channel 2", source="run:run2")
        released = claims_mod.unclaim_by_source(self.root, "run:run1")
        self.assertEqual(released, 0)
        self.assertIn(2, claims_mod.read_all(self.root))


if __name__ == "__main__":
    unittest.main()
