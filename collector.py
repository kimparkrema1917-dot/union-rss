#!/usr/bin/env python3
"""Public board → per-organization RSS. Python 3.9+, no account or API key."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
import html
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
ATOM = "http://www.w3.org/2005/Atom"
ET.register_namespace("atom", ATOM)
MAX_RESPONSE = 5 * 1024 * 1024


class CollectionError(Exception):
    pass


class RobotsBlocked(CollectionError):
    pass


def clean(value):
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", "", str(value))
    return " ".join(text.split())


def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def from_iso(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result if result.tzinfo else result.replace(tzinfo=KST)


def day_from_text(text):
    match = re.search(r"(?<!\d)(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})(?!\d)", text)
    if not match:
        raise CollectionError("게시물 날짜 형식이 바뀌었습니다: " + clean(text)[:80])
    return datetime(*map(int, match.groups()), tzinfo=KST).isoformat()


def safe_url(base, link):
    url = urljoin(base, link)
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or parts.hostname != urlsplit(base).hostname:
        raise CollectionError("예상하지 않은 게시물 주소: " + url[:180])
    return url


def article(source, key, title, url, published, summary="", category="", date_basis="published_day"):
    title = clean(title)
    if not title or not published:
        raise CollectionError("제목 또는 날짜가 없는 게시물이 발견됐습니다.")
    from_iso(published)  # Reject malformed timestamps instead of silently inventing a date.
    return {
        "id": str(key), "title": title, "url": safe_url(source["url"], url),
        "published": published, "summary": clean(summary)[:600],
        "category": category or source["section"], "date_basis": date_basis,
    }


def parse_kptu(source, soup):
    items = []
    for row in soup.select(".news_list > li"):
        link = row.select_one('a[href*="detail.aspx"]')
        title, date = row.select_one(".tit"), row.select_one(".date")
        if not link or not title or not date:
            raise CollectionError("공공운수노조 목록의 제목·날짜 구조를 확인해야 합니다.")
        query = parse_qs(urlsplit(link["href"]).query)
        if query.get("mid") != ["BCB52DDC"] or not query.get("idx", [""])[0].isdigit():
            continue
        key = query["idx"][0]
        url = "/board/detail.aspx?" + urlencode({"mid": "BCB52DDC", "idx": key})
        summary = row.select_one(".txt")
        items.append(article(source, key, title.get_text(" ", strip=True), url,
                             day_from_text(date.get_text()), summary.get_text(" ", strip=True) if summary else ""))
    return items


def parse_kmwu(source, soup):
    items = []
    for row in soup.select("tr"):
        link = row.select_one(".td_subject a[href]")
        if not link:
            continue
        query = parse_qs(urlsplit(link["href"]).query)
        if query.get("bo_table") != ["ce_B12"] or not query.get("wr_id", [""])[0].isdigit():
            continue
        if "bo_notice" in row.get("class", []) and not source.get("include_pinned", False):
            continue
        date = row.select_one(".td_date, .td_datetime")
        if date is None:
            raise CollectionError("금속노조 게시물 날짜를 찾지 못했습니다.")
        key = query["wr_id"][0]
        url = "/bbs/board.php?" + urlencode({"bo_table": "ce_B12", "wr_id": key})
        title = link.get_text(" ", strip=True)
        if title.endswith("…") or title.endswith("..."):
            raise CollectionError("금속노조 제목이 잘린 화면입니다. fetch_url의 device=pc를 확인하세요.")
        items.append(article(source, key, title, url, day_from_text(date.get_text())))
    return items


def parse_leftall(source, soup):
    items = []
    for row in soup.select(".card-body"):
        link = row.select_one(".card-title a[href]")
        if not link:
            continue
        url = safe_url(source["url"], link["href"])
        match = re.fullmatch(r"/newsletter/(\d+)/?", urlsplit(url).path)
        query = parse_qs(urlsplit(url).query)
        key = match.group(1) if match else query.get("wr_id", [""])[0]
        if not match and query.get("bo_table") != ["newsletter"]:
            continue
        if not key.isdigit():
            continue
        date = row.select_one(".text-right")
        if date is None:
            raise CollectionError("전국결집 게시물 날짜를 찾지 못했습니다.")
        # Only read the date column: the title itself may contain a different date.
        items.append(article(source, key, link.get_text(" ", strip=True),
                             "/newsletter/" + key, day_from_text(date.get_text())))
    return items


def rich_text(value):
    return clean("".join(str(part[0]) for part in value or [] if isinstance(part, list) and part))


def result_ids(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "blockIds" and isinstance(child, list):
                yield from (x for x in child if isinstance(x, str))
            elif isinstance(child, (dict, list)):
                yield from result_ids(child)
    elif isinstance(value, list):
        for child in value:
            yield from result_ids(child)


def parse_oopy(source, soup):
    script = soup.select_one("script#__NEXT_DATA__")
    if script is None:
        raise CollectionError("기후정의동맹의 공개 페이지 데이터 형식이 바뀌었습니다.")
    props = json.loads(script.get_text())["props"]["pageProps"]
    record_map = props["recordMap"]
    wanted = set(source["collections"])
    collections = {}
    for key, record in record_map.get("collection", {}).items():
        value = record.get("value", {})
        name = rich_text(value.get("name"))
        if name in wanted:
            collections[key] = "활동 소식" if name == "소식" else name
    if len(collections) != len(wanted):
        raise CollectionError("기후정의동맹의 수집 대상 목록 이름이 바뀌었습니다.")
    blocks = dict(record_map.get("block", {}))
    visible_ids = set()
    for query in props.get("queryCollectionResult", {}).values():
        visible_ids.update(result_ids(query.get("result", {})))
        blocks.update(query.get("recordMap", {}).get("block", {}))
    items = []
    covered = set()
    # Restrict to public collection query results, excluding templates and unrelated pages.
    for key in visible_ids:
        value = blocks.get(key, {}).get("value", {})
        parent = value.get("parent_id")
        if (value.get("type") != "page" or value.get("parent_table") != "collection"
                or parent not in collections or value.get("alive") is False):
            continue
        if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", key):
            continue
        title = rich_text(value.get("properties", {}).get("title"))
        created = value.get("created_time")
        if not title or not isinstance(created, (int, float)) or created <= 0:
            raise CollectionError("기후정의동맹 게시물의 제목·생성 시각이 없습니다.")
        date = datetime.fromtimestamp(created / 1000, KST).isoformat()
        items.append(article(source, key, title, "/" + key, date,
                             category=collections[parent], date_basis="page_created"))
        covered.add(parent)
    if covered != set(collections):
        raise CollectionError("기후정의동맹의 일부 목록을 읽지 못했습니다. 기존 피드를 유지합니다.")
    return items


PARSERS = {"kptu": parse_kptu, "kmwu": parse_kmwu, "leftall": parse_leftall, "oopy": parse_oopy}


def parse_source(source, content):
    soup = BeautifulSoup(content, "html.parser")
    items = PARSERS[source["kind"]](source, soup)
    if not items:
        raise CollectionError("게시물을 0건 읽었습니다. 사이트 구조 또는 접근 상태를 확인하세요.")
    unique = {item["id"]: item for item in items}
    return sorted(unique.values(), key=lambda x: (x["published"], x["id"]), reverse=True)


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


def save_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


class Fetcher:
    def __init__(self, robots_cache, user_agent="UnionRSS/1.0", sleep=time.sleep, clock=time.time):
        self.cache = robots_cache
        self.agent = user_agent
        self.sleep, self.clock = sleep, clock
        self.last_request = {origin: entry["last_request"] for origin, entry in robots_cache.items()
                             if "last_request" in entry}
        self.delays = {}

    def request(self, url):
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(url))
        last = self.last_request.get(origin)
        wait = self.delays.get(origin, 2) - (self.clock() - last) if last is not None else 0
        if wait > 0:
            print(f"방문 간격 준수: {urlsplit(url).hostname} {wait:.0f}초 대기", flush=True)
            self.sleep(wait)
        self.last_request[origin] = self.clock()
        if origin in self.cache:
            self.cache[origin]["last_request"] = self.last_request[origin]
        request = Request(url, headers={"User-Agent": self.agent, "Accept": "text/html, text/plain;q=0.9, */*;q=0.1"})
        with urlopen(request, timeout=30) as response:
            if urlsplit(response.url).hostname != urlsplit(url).hostname:
                raise CollectionError("다른 도메인으로 이동했습니다. 수집 설정을 확인하세요.")
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise CollectionError("응답이 5MB 제한을 초과했습니다.")
            encoding = response.headers.get_content_charset() or "utf-8"
            return raw.decode(encoding, errors="replace")

    def policy(self, url):
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(url))
        record = self.cache.get(origin)
        if not record or self.clock() - record["checked_at"] >= 86400:
            try:
                text = self.request(origin + "/robots.txt")
                if "<html" in text.lower() or "<!doctype" in text.lower():
                    raise CollectionError("robots.txt 대신 HTML이 반환되어 수집을 보류합니다.")
            except HTTPError as error:
                if error.code in (404, 410):
                    text = "User-agent: *\nAllow: /\n"
                elif error.code in (401, 403):
                    text = "User-agent: *\nDisallow: /\n"
                else:
                    raise CollectionError(f"robots.txt 확인 실패: HTTP {error.code}") from error
            record = {"checked_at": self.clock(), "text": text,
                      "last_request": self.last_request.get(origin, self.clock())}
            self.cache[origin] = record
        robot = RobotFileParser()
        robot.parse(record["text"].splitlines())
        delay = robot.crawl_delay(self.agent) or 2
        rate = robot.request_rate(self.agent)
        if rate and rate.requests:
            delay = max(delay, rate.seconds / rate.requests)
        self.delays[origin] = max(2, delay)
        if not robot.can_fetch(self.agent, url):
            raise RobotsBlocked("robots.txt가 UnionRSS의 자동 수집을 허용하지 않습니다.")

    def get(self, url):
        self.policy(url)
        for attempt in range(2):
            try:
                return self.request(url)
            except HTTPError as error:
                if attempt or error.code not in (429, 500, 502, 503, 504):
                    raise
                retry_after = error.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    # Defer to the next hourly run for long server-requested delays.
                    if int(retry_after) > 300:
                        raise CollectionError("서버가 긴 대기 시간을 요청했습니다. 다음 실행에 재시도합니다.") from error
                    self.sleep(int(retry_after))
            except (URLError, TimeoutError):
                if attempt:
                    raise
        raise CollectionError("요청에 실패했습니다.")


def merge_items(previous, incoming, now, limit):
    merged = {item["id"]: dict(item) for item in previous}
    new_count = 0
    for item in incoming:
        old = merged.get(item["id"])
        first_seen = old.get("first_seen", now) if old else now
        merged[item["id"]] = dict(item, first_seen=first_seen)
        if old is None:
            new_count += 1
    result = sorted(merged.values(), key=lambda x: (x["published"], x["id"]), reverse=True)
    return result[:limit], new_count


def collect(sources, state, fetcher, now, limit):
    errors = 0
    records = state.setdefault("sources", {})
    for source in sources:
        key = source["id"]
        old = records.get(key, {})
        record = dict(old, last_attempt=now)
        record.setdefault("items", [])
        try:
            incoming = parse_source(source, fetcher.get(source.get("fetch_url", source["url"])))
            items, new_count = merge_items(record["items"], incoming, now, limit)
            record.update(items=items, status="ok", message="정상 수집", last_success=now,
                          fetched_count=len(incoming), new_count=new_count)
            print(f"{source['name']}: 확인 {len(incoming)}건 / 새 글 {new_count}건 / 보관 {len(items)}건", flush=True)
        except RobotsBlocked as error:
            record.update(status="blocked", message=str(error), new_count=0)
            # The known KPTU restriction is visible, without sending an hourly failure alert.
            if not source.get("expected_robots_block", False):
                errors += 1
            print(f"{source['name']}: 수집 보류 — {error}", flush=True)
        except Exception as error:
            errors += 1
            record.update(status="error", message=clean(str(error))[:250], new_count=0)
            print(f"{source['name']}: 실패, 기존 {len(record['items'])}건 유지 — {error}", file=sys.stderr, flush=True)
        records[key] = record
    return errors


def rss_document(source, record, base_url=""):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    def add(parent, tag, value):
        ET.SubElement(parent, tag).text = clean(value)
    add(channel, "title", source["name"] + " · " + source["section"])
    add(channel, "link", source["url"])
    description = "비공식 RSS · " + source["section"] + " · 제목과 원문 링크를 제공합니다."
    if record.get("status") != "ok":
        description += " 수집 상태: " + record.get("message", "아직 수집하지 않았습니다.")
    add(channel, "description", description)
    add(channel, "language", "ko-kr")
    add(channel, "generator", "UnionRSS 1.0")
    add(channel, "ttl", "60")
    if record.get("last_success"):
        add(channel, "lastBuildDate", format_datetime(from_iso(record["last_success"])))
    if base_url:
        ET.SubElement(channel, "{" + ATOM + "}link", {
            "href": base_url.rstrip("/") + "/feeds/" + source["id"] + ".xml",
            "rel": "self", "type": "application/rss+xml",
        })
    for entry in record.get("items", []):
        item = ET.SubElement(channel, "item")
        add(item, "title", entry["title"])
        add(item, "link", entry["url"])
        guid = ET.SubElement(item, "guid", isPermaLink="false")
        guid.text = "urn:union-rss:" + source["id"] + ":" + entry["id"]
        add(item, "pubDate", format_datetime(from_iso(entry["published"])))
        add(item, "category", entry["category"])
        note = ("시각은 원문 페이지 생성 시각이며 실제 발표 시각과 다를 수 있습니다."
                if entry["date_basis"] == "page_created" else "원문에 날짜만 표시되어 시각은 한국시간 00:00으로 표기합니다.")
        body = ("<p>" + html.escape(entry["summary"]) + "</p>" if entry["summary"] else "")
        body += '<p><a href="' + html.escape(entry["url"], quote=True) + '">원문 읽기</a></p>'
        body += "<p>" + html.escape(note) + "</p>"
        add(item, "description", body)
    ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="unicode", xml_declaration=True) + "\n"


def render_site(sources, state, target, base_url, now):
    target.mkdir(parents=True, exist_ok=True)
    cards = []
    public_status = {"checked_at": now, "sources": {}}
    for source in sources:
        key = source["id"]
        record = state.get("sources", {}).get(key, {"items": [], "status": "pending"})
        atomic_write(target / "feeds" / (key + ".xml"), rss_document(source, record, base_url))
        status = {k: v for k, v in record.items() if k != "items"}
        status["item_count"] = len(record.get("items", []))
        public_status["sources"][key] = status
        label = {"ok": "정상", "blocked": "수집 보류", "error": "오류 · 기존 글 유지", "pending": "수집 전"}[record["status"]]
        latest = "".join('<li><a href="' + html.escape(item["url"], quote=True) + '">' + html.escape(item["title"]) + "</a></li>"
                         for item in record.get("items", [])[:3])
        last = record.get("last_success")
        last = from_iso(last).astimezone(KST).strftime("%Y-%m-%d %H:%M KST") if last else "아직 없음"
        cards.append(f'''<article><span class="badge {record['status']}">{html.escape(label)}</span>
<h2>{html.escape(source['name'])}</h2><p>{html.escape(source['section'])}</p>
<p><a class="feed" href="feeds/{key}.xml">RSS 구독 주소</a> <a href="{html.escape(source['url'], quote=True)}">원문 게시판 ↗</a></p>
<p class="small">보관 {len(record.get('items', []))}건 · 마지막 성공 {last}</p>
<p class="small">{html.escape(record.get('message', ''))}</p><ul>{latest}</ul></article>''')
    page = '''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>단체별 새 글 · RSS</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f3ec;color:#17312b;font-family:system-ui,-apple-system,sans-serif;line-height:1.65}
main{max-width:1000px;margin:auto;padding:56px 24px}header{margin-bottom:32px}h1{font-size:clamp(28px,5vw,42px);letter-spacing:-.05em;margin:4px 0}
h2{font-size:24px;margin:12px 0 4px}p{margin:8px 0}a{color:#176b51;text-underline-offset:4px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:18px}
article{padding:26px;border:1px solid #d5ddd5;border-radius:14px;background:#fff}.small,footer{font-size:13px;color:#59655f}.badge{display:inline-block;font-size:12px;padding:3px 10px;border-radius:20px;background:#eee}.ok{background:#e1f4e8}.blocked,.error{background:#fff0d4;color:#79430c}.feed{font-weight:700;margin-right:12px}ul{padding-left:20px;font-size:14px}li{margin:10px 0}footer{margin-top:28px}code{overflow-wrap:anywhere}
</style></head><body><main><header><p>PUBLIC BOARD READER</p><h1>단체별 새 글, 한곳에서.</h1>
<p>원하는 단체의 RSS 주소를 복사해 RSS 리더에 추가하세요.</p>
<p class="small">매시간 확인 · 단체별 최근 글 보관 · 비공식 피드</p></header><section class="grid">'''
    page += "".join(cards) + '''</section><footer><p>기후정의동맹은 알립니다·성명 및 자료·활동 소식을 함께 제공합니다.
일부 피드가 보류 중이면 구독 주소는 열리더라도 새 글이 수집되지 않습니다.</p>
<p>게시물 저작권은 원저작자에게 있습니다. 제목·목록 요약과 원문 링크를 제공합니다. <a href="feeds.opml">모든 피드 가져오기(OPML)</a> · <a href="status.json">수집 상태</a></p></footer></main></body></html>'''
    atomic_write(target / "index.html", page)
    atomic_write(target / ".nojekyll", "")
    save_json(target / "status.json", public_status)
    opml = ET.Element("opml", version="2.0")
    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = "단체별 RSS"
    body = ET.SubElement(opml, "body")
    for source in sources:
        ET.SubElement(body, "outline", text=source["name"], title=source["name"], type="rss",
                      xmlUrl=base_url.rstrip("/") + "/feeds/" + source["id"] + ".xml" if base_url else "feeds/" + source["id"] + ".xml",
                      htmlUrl=source["url"])
    ET.indent(opml, space="  ")
    atomic_write(target / "feeds.opml", ET.tostring(opml, encoding="unicode", xml_declaration=True) + "\n")


def write_summary(sources, state):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## RSS 수집 결과", "", "| 단체 | 상태 | 보관 |", "|---|---|---|"]
    for source in sources:
        record = state["sources"][source["id"]]
        lines.append(f"| {source['name']} | {record['status']} | {len(record['items'])}건 |")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "sources.json")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=ROOT / "site")
    parser.add_argument("--base-url", default=os.environ.get("SITE_URL", ""))
    parser.add_argument("--render-only", action="store_true", help="저장된 데이터로만 피드 재생성")
    args = parser.parse_args(argv)
    if args.base_url and (urlsplit(args.base_url).scheme not in ("http", "https") or not urlsplit(args.base_url).netloc):
        parser.error("--base-url은 https://로 시작하는 공개 사이트 주소여야 합니다.")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    sources = config["sources"]
    ids = [source["id"] for source in sources]
    if len(ids) != len(set(ids)) or not all(re.fullmatch(r"[a-z0-9_-]+", key) for key in ids):
        parser.error("단체 id는 중복 없는 영문 소문자·숫자·밑줄·하이픈이어야 합니다.")
    limit = config.get("max_items", 200)
    if not isinstance(limit, int) or limit < 1:
        parser.error("max_items는 양의 정수여야 합니다.")
    state_path = args.data_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"version": 1, "sources": {}, "robots": {}}
    now, errors = iso_now(), 0
    if not args.render_only:
        contact = os.environ.get("RSS_CONTACT_URL", "")
        agent = "UnionRSS/1.0" + (" (+" + contact + ")" if contact else "")
        fetcher = Fetcher(state.setdefault("robots", {}), user_agent=agent)
        errors = collect(sources, state, fetcher, now, limit)
        save_json(state_path, state)
    render_site(sources, state, args.output, args.base_url, now)
    if not args.render_only:
        write_summary(sources, state)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
