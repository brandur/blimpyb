import sys
from pathlib import Path
import unittest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from recover import article_id, image_family, url_key
from build import prepare_content, feed_documents, collect_tags


class EmptyAssets:
    def find(self, url, doc=None):
        return None


class ArchiveTests(unittest.TestCase):
    def test_tag_pages_use_explicit_metadata_and_links_stay_local(self):
        docs = [
            dict(id="article", original="http://blimpyb.com/travel/story/123/", html='''
                <p>Tags: <a rel="tag" href="https://web.archive.org/web/20140202/http://blimpyb.com/tag/washington-state/">Washington State</a>
                | <a rel="tag" href="/tag/mcdonalds/">McDonald's</a>
                | <a rel="tag" href="http://www.blimpyb.com:80/tag/washington-state/">Washington State</a></p>'''),
            dict(id="gallery", original="http://blimpyb.com/gallery/coast/", html='<a rel="tag" href="/tag/washington-state/">Washington State</a>'),
            dict(id="feed", original="http://blimpyb.com/travel/feed-story/456/", html='<p>Feed article.</p>', tags=["WASHINGTON STATE", "C++", "C#"]),
            dict(id="mention", original="http://blimpyb.com/travel/other/789/", html='<p>Just mentioning Washington State.</p>'),
        ]
        tags, links = collect_tags(docs)
        washington = tags["tag:washington-state"]
        self.assertEqual([d["id"] for d in washington["documents"]], ["article", "gallery", "feed"])
        self.assertEqual(washington["path"], "tags/washington-state.html")
        self.assertNotEqual(tags["feed:c++"]["path"], tags["feed:c#"]["path"])
        prepare_content(docs[0], EmptyAssets(), links, {})
        hrefs = {a["href"] for a in BeautifulSoup(docs[0]["body"], "html.parser").select("a[href]")}
        self.assertEqual(hrefs, {"../tags/washington-state.html", "../tags/mcdonalds.html"})

    def test_rss_full_content_is_recovered_but_excerpts_are_not(self):
        xml = b'''<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
        <item><title>Recovered story</title><link>http://blimpyb.com/random/story/123/</link>
        <pubDate>Tue, 03 May 2011 12:00:00 +0000</pubDate><description>Excerpt...</description>
        <content:encoded><![CDATA[<p>Full original story.</p><img src="photo.jpg">]]></content:encoded></item>
        <item><title>Only an excerpt</title><link>http://blimpyb.com/random/other/456/</link>
        <pubDate>Tue, 03 May 2011 12:00:00 +0000</pubDate><description>Excerpt...</description></item>
        </channel></rss>'''
        docs = feed_documents(xml, {"source": "https://web.archive.org/source", "path": "archive/raw/feed.xml"})
        self.assertEqual([d["id"] for d in docs], ["123"])
        self.assertIn("Full original story.", docs[0]["html"])
        self.assertEqual(docs[0]["date"], "2011-05-03")

    def test_atom_content_is_recovered_but_summaries_are_not(self):
        xml = b'''<feed xmlns="http://www.w3.org/2005/Atom">
        <entry><title>Atom story</title><link rel="alternate" href="http://blimpyb.com/random/story/123/"/>
        <published>2010-09-11T20:09:02Z</published><summary>Short excerpt</summary>
        <content type="html">&lt;p&gt;Full Atom story.&lt;/p&gt;</content></entry>
        <entry><title>Summary only</title><link rel="alternate" href="http://blimpyb.com/random/story/456/"/>
        <published>2010-09-11T20:09:02Z</published><summary>Only an excerpt</summary></entry></feed>'''
        docs = feed_documents(xml, {"source": "https://web.archive.org/source", "path": "archive/raw/atom.xml"})
        self.assertEqual([d["id"] for d in docs], ["123"])
        self.assertEqual(docs[0]["html"], "<p>Full Atom story.</p>")
        self.assertEqual(docs[0]["date"], "2010-09-11")

    def test_wordpress_and_pagespeed_variants_match_without_crossing_months(self):
        full = "http://blimpyb.com/wp-content/uploads/2012/02/IMG_7430.jpg"
        small = "https://web.archive.org/web/20130202im_/http://blimpyb.com:80/wp-content/uploads/2012/02/238x158xIMG_7430-600x400.jpg.pagespeed.ic.abc.jpg"
        self.assertEqual(image_family(full), image_family(small))
        self.assertNotEqual(image_family(full), image_family(full.replace("2012/02", "2010/02")))

    def test_index_pages_and_spam_are_not_articles(self):
        self.assertEqual(article_id("http://blimpyb.com/random/story/123/"), "123")
        self.assertEqual(article_id("http://blimpyb.com/?p=123"), "123")
        self.assertIsNone(article_id("http://blimpyb.com/date/2010/02/"))
        self.assertIsNone(article_id("http://blimpyb.com/category/random/page/2/"))
        self.assertIsNone(article_id("http://blimpyb.com/wpinc/spam/123/"))
        self.assertIsNone(article_id("http://unrelated.example/random/story/123/"))

    def test_url_normalization(self):
        self.assertEqual(url_key("http://www.blimpyb.com:80/a/"), url_key("https://blimpyb.com/a"))

    def test_rendering_removes_active_content_and_keeps_captions_and_links(self):
        doc = dict(original="http://blimpyb.com/random/story/123/", html='''
          <script>alert(1)</script><style>body{display:none}</style>
          <iframe src="https://tracker.example"></iframe>
          <object data="http://obsolete.example/player.swf"><embed src="http://obsolete.example/player.swf"></object>
          <p onclick="alert(1)">Original text <a href="javascript:alert(1)">bad</a></p>
          <div class="wp-caption" style="width:30px"><a href="http://blimpyb.com/a.jpg"><img src="http://blimpyb.com/a.jpg" title="Original alt" onerror="alert(1)"></a><p class="wp-caption-text">Original caption</p></div>
          <a href="http://blimpyb.com/random/other/456/">Another article</a>
          <a href="http://blimpyb.com/gallery/missing/">Unrecovered gallery</a>''')
        prepare_content(doc, EmptyAssets(), {}, {"456": "articles/other.html"})
        soup = BeautifulSoup(doc["body"], "html.parser")
        self.assertFalse(soup.select("script, style, iframe, img"))
        self.assertNotIn("onclick", doc["body"])
        self.assertNotIn("javascript:", doc["body"])
        self.assertIn("Original text", soup.get_text())
        self.assertEqual(soup.figcaption.get_text(), "Original caption")
        self.assertIn("../articles/other.html", doc["body"])
        self.assertIn("https://web.archive.org/web/2014/http://blimpyb.com/gallery/missing/", doc["body"])
        self.assertEqual(doc["missing"], [{"original": "http://blimpyb.com/a.jpg", "alt": "Original alt"}])


if __name__ == "__main__":
    unittest.main()
