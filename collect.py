#!/usr/bin/env python3
"""
CalTeach social tracker: daily collector.

Pulls Instagram stats from Meta's Graph API, merges hand-entered LinkedIn
numbers, and writes JSON files the dashboard (docs/index.html) reads.

  python collect.py          real run (needs IG_USER_ID + IG_ACCESS_TOKEN env vars)
  python collect.py --demo   sample data, to preview the dashboard

Optional env: BACKFILL_DAYS (default 60), how far back to fill in daily stats
on the first run, so charts and "vs. last period" work right away.
"""
import csv, json, os, re, sys, random, urllib.request, urllib.parse, urllib.error
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "docs", "data")
HISTORY = os.path.join(DATA, "history.json")    # one row per platform per day
POSTS = os.path.join(DATA, "posts.json")        # posts, reels, stories with their stats
AUDIENCE = os.path.join(DATA, "audience.json")  # follower age / gender / city
META = os.path.join(DATA, "meta.json")          # last run, account info, de-duplicated reach
MANUAL_LI = os.path.join(ROOT, "manual", "linkedin.csv")

GRAPH = "https://graph.facebook.com/v23.0"
BACKFILL_DAYS = int(os.environ.get("BACKFILL_DAYS", "60"))
TODAY = date.today()


# ---------- helpers ----------
def get(url, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"HTTP {e.code} {url.split('?')[0].rsplit('/', 2)[-2:]}: {body}") from None


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=1)


def merge(history, row):
    """Add a row, or update the existing row for the same date + platform."""
    for h in history:
        if h["date"] == row["date"] and h["platform"] == row["platform"]:
            h.update({k: v for k, v in row.items() if v is not None})
            return
    history.append({k: v for k, v in row.items() if v is not None})


def ts(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def regroup(by, idx):
    """{'FOLLOWER|POST': 5, ...} -> totals keyed by one dimension."""
    out = {}
    for k, v in (by or {}).items():
        parts = k.split("|")
        if idx < len(parts):
            out[parts[idx]] = out.get(parts[idx], 0) + v
    return out or None


def fill_followers(history, platform="instagram"):
    """Estimate past follower counts from the latest real count and daily follows/unfollows."""
    rows = sorted((h for h in history if h["platform"] == platform), key=lambda h: h["date"], reverse=True)
    known = None
    for i, r in enumerate(rows):
        if r.get("followers") is not None and not r.get("followers_est"):
            known = r["followers"]
            continue
        if known is None:
            continue
        newer = rows[i - 1] if i else None
        if newer is None:
            break
        if newer["date"] == TODAY.isoformat():   # snapshot is taken in the morning, so ~ end of yesterday
            net = 0
        elif newer.get("follows") is not None:
            net = newer["follows"] - (newer.get("unfollows") or 0)
        else:
            break
        known -= net
        r["followers"], r["followers_est"] = known, True
    history.sort(key=lambda h: (h["date"], h["platform"]))


# ---------- Instagram ----------
class Instagram:
    def __init__(self, uid, tok):
        self.uid, self.tok, self.warned, self.post_metrics = uid, tok, set(), {}

    def call(self, path, **params):
        params["access_token"] = self.tok
        return get(f"{GRAPH}/{path}", params)

    def warn(self, what, e):
        if what not in self.warned:
            self.warned.add(what)
            print(f"  note: {what} unavailable ({str(e)[:160]})")

    def totals(self, metrics, since, until, breakdown=None):
        """Account insights as total_value for [since, until). Returns {metric: value, metric_by: {...}}."""
        def fetch(ms, bd):
            p = dict(metric=",".join(ms), period="day", metric_type="total_value", since=since, until=until)
            if bd:
                p["breakdown"] = bd
            out = {}
            for item in self.call(f"{self.uid}/insights", **p).get("data", []):
                tv = item.get("total_value") or {}
                out[item["name"]] = tv.get("value")
                for b in tv.get("breakdowns", []):
                    out[item["name"] + "_by"] = {"|".join(r["dimension_values"]): r["value"] for r in b.get("results", [])}
            return out
        try:
            return fetch(metrics, breakdown)
        except Exception:
            out = {}
            for m in metrics:          # one bad metric shouldn't sink the rest
                try:
                    out.update(fetch([m], breakdown))
                except Exception as e:
                    if breakdown:
                        try:
                            out.update(fetch([m], None)); continue
                        except Exception:
                            pass
                    self.warn(f"{m} ({breakdown or 'total'})", e)
            return out

    def account(self):
        return self.call(self.uid, fields="username,followers_count,media_count,profile_picture_url")

    def day(self, d):
        since, until = ts(d), ts(d) + 86400
        row = {"date": d.isoformat(), "platform": "instagram"}
        t = self.totals(["reach", "profile_views", "accounts_engaged"], since, until)
        row.update(reach=t.get("reach"), profile_views=t.get("profile_views"), accounts_engaged=t.get("accounts_engaged"))

        v = self.totals(["views"], since, until, breakdown="follow_type,media_product_type")
        if v.get("views_by") and all("|" in k for k in v["views_by"]):
            row["views_cross"] = v["views_by"]
            row["views_by_follow"], row["views_by_type"] = regroup(v["views_by"], 0), regroup(v["views_by"], 1)
        else:
            a = self.totals(["views"], since, until, breakdown="follow_type")
            b = self.totals(["views"], since, until, breakdown="media_product_type")
            row["views_by_follow"], row["views_by_type"] = a.get("views_by"), b.get("views_by")
            v = v or a or b
        row["views"] = v.get("views")

        im = ["total_interactions", "likes", "comments", "shares", "saves", "reposts"]
        i = self.totals(im, since, until, breakdown="media_product_type")
        row["interactions"], row["interactions_by_type"] = i.get("total_interactions"), i.get("total_interactions_by")
        for m in im[1:]:
            row[m], row[m + "_by_type"] = i.get(m), i.get(m + "_by")

        f = self.totals(["follows_and_unfollows"], since, until, breakdown="follow_type").get("follows_and_unfollows_by") or {}
        row["follows"], row["unfollows"] = f.get("FOLLOWER"), f.get("NON_FOLLOWER")
        return row

    def period_reach(self, days, offset=0):
        """De-duplicated unique accounts reached over a whole period (can't be added up from daily)."""
        end = TODAY - timedelta(days=offset)
        return self.totals(["reach"], ts(end - timedelta(days=days)), ts(end)).get("reach")

    def audience(self):
        out = {}
        try:
            r = self.call(f"{self.uid}/insights", metric="follower_demographics", period="lifetime",
                          timeframe="this_month", breakdown="age,gender", metric_type="total_value")
            res = r["data"][0]["total_value"]["breakdowns"][0]["results"]
            out["age_gender"] = {"|".join(x["dimension_values"]): x["value"] for x in res}
        except Exception as e:
            self.warn("follower age/gender", e)
        try:
            r = self.call(f"{self.uid}/insights", metric="follower_demographics", period="lifetime",
                          timeframe="this_month", breakdown="city", metric_type="total_value")
            res = r["data"][0]["total_value"]["breakdowns"][0]["results"]
            out["city"] = dict(sorted(((x["dimension_values"][0], x["value"]) for x in res), key=lambda kv: -kv[1])[:8])
        except Exception as e:
            self.warn("follower cities", e)
        return out

    def media_stats(self, mid, kind, wanted):
        """Per-post insights. Learns which metrics each post type supports, so it isn't 6 calls per post."""
        ms = self.post_metrics.get(kind, wanted)
        try:
            r = self.call(f"{mid}/insights", metric=",".join(ms))
            return {x["name"]: x["values"][0]["value"] for x in r.get("data", [])}
        except Exception:
            ok, out = [], {}
            for m in ms:
                try:
                    r = self.call(f"{mid}/insights", metric=m)
                    out[m] = r["data"][0]["values"][0]["value"]; ok.append(m)
                except Exception:
                    pass
            self.post_metrics[kind] = ok
            return out

    def posts(self):
        fields = "id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count"
        out = []
        for p in self.call(f"{self.uid}/media", fields=fields, limit=40).get("data", []):
            kind = p.get("media_product_type") or "FEED"
            s = self.media_stats(p["id"], kind, ["reach", "views", "saved", "shares", "total_interactions", "reposts"])
            out.append(post_row(p, kind, s, likes=p.get("like_count"), comments=p.get("comments_count")))
        return out

    def stories(self):
        """Stories only exist for 24h, so each daily run saves whatever is live."""
        fields = "id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,timestamp"
        out = []
        for p in self.call(f"{self.uid}/stories", fields=fields).get("data", []):
            s = self.media_stats(p["id"], "STORY", ["reach", "views", "replies", "shares", "total_interactions"])
            out.append(post_row(p, "STORY", s))
        return out


def post_row(p, kind, s, likes=None, comments=None):
    return {"platform": "instagram", "id": p["id"], "ts": p.get("timestamp"), "date": (p.get("timestamp") or "")[:10],
            "type": kind, "text": (p.get("caption") or "").split("\n")[0][:120], "url": p.get("permalink"),
            "thumb": p.get("thumbnail_url") or p.get("media_url") if p.get("media_type") != "VIDEO" or p.get("thumbnail_url") else None,
            "views": s.get("views"), "reach": s.get("reach"), "likes": likes, "comments": comments,
            "shares": s.get("shares"), "saves": s.get("saved"), "reposts": s.get("reposts"),
            "replies": s.get("replies"), "interactions": s.get("total_interactions")}


# ---------- LinkedIn company page (API) ----------
# Needs LinkedIn's Community Management API (free, but LinkedIn has to approve the app).
LI_API = "https://api.linkedin.com/rest"


def li_versions():
    """LinkedIn wants a YYYYMM API version and retires old ones after about a year. Try recent months."""
    if os.environ.get("LI_API_VERSION"):
        return [os.environ["LI_API_VERSION"]]
    y, m, out = TODAY.year, TODAY.month, []
    for _ in range(14):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y}{m:02d}")
    return out


def li_ms(d):
    return ts(d) * 1000


def li_text(t):
    t = re.sub(r"\{hashtag\|\\?#\|([^}]+)\}", r"#\1", t or "")      # LinkedIn's hashtag markup
    t = re.sub(r"@\[([^\]]+)\]\([^)]*\)", r"\1", t)                 # @mentions
    return t.split("\n")[0][:120]


class LinkedIn:
    def __init__(self, org, tok):
        self.urn = f"urn:li:organization:{org}"
        self.enc = urllib.parse.quote(self.urn, safe="")
        self.tok, self.version, self.warned = tok, None, set()

    def call(self, path):
        last = None
        for v in ([self.version] if self.version else li_versions()):
            req = urllib.request.Request(f"{LI_API}/{path}", headers={
                "Authorization": f"Bearer {self.tok}", "LinkedIn-Version": v, "X-Restli-Protocol-Version": "2.0.0"})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    self.version = v
                    return json.load(r)
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")[:300]
                if e.code in (400, 426) and "version" in body.lower():
                    last = body; continue                     # that version is retired or not out yet
                if e.code == 401:
                    raise RuntimeError("LinkedIn access key expired or invalid (they last 60 days). Generate a new one.") from None
                raise RuntimeError(f"HTTP {e.code} {path.split('?')[0]}: {body}") from None
        raise RuntimeError(f"No working LinkedIn-Version found: {last}")

    def warn(self, what, e):
        if what not in self.warned:
            self.warned.add(what); print(f"  note: LinkedIn {what} unavailable ({str(e)[:160]})")

    def followers(self):
        return self.call(f"networkSizes/{self.enc}?edgeType=COMPANY_FOLLOWED_BY_MEMBER").get("firstDegreeSize")

    def daily(self, start, end):
        """Per-day page stats for [start, end). Three calls cover the whole range."""
        ti = f"(timeRange:(start:{li_ms(start)},end:{li_ms(end)}),timeGranularityType:DAY)"
        rows = {}
        def row(el):
            d = datetime.fromtimestamp(el["timeRange"]["start"] / 1000, tz=timezone.utc).date().isoformat()
            return rows.setdefault(d, {"date": d, "platform": "linkedin", "src": "api"})
        try:
            for el in self.call(f"organizationalEntityShareStatistics?q=organizationalEntity&organizationalEntity={self.enc}&timeIntervals={ti}").get("elements", []):
                s, r = el.get("totalShareStatistics", {}), row(el)
                r.update(impressions=s.get("impressionCount"), reach=s.get("uniqueImpressionsCount"),
                         clicks=s.get("clickCount"), likes=s.get("likeCount"), comments=s.get("commentCount"),
                         shares=s.get("shareCount"),
                         engagements=sum(s.get(k) or 0 for k in ("clickCount", "likeCount", "commentCount", "shareCount")))
        except Exception as e:
            self.warn("post stats", e)
        try:
            for el in self.call(f"organizationalEntityFollowerStatistics?q=organizationalEntity&organizationalEntity={self.enc}&timeIntervals={ti}").get("elements", []):
                g = el.get("followerGains", {})
                row(el)["follows"] = (g.get("organicFollowerGain") or 0) + (g.get("paidFollowerGain") or 0)
        except Exception as e:
            self.warn("follower gains", e)
        try:
            for el in self.call(f"organizationPageStatistics?q=organization&organization={self.enc}&timeIntervals={ti}").get("elements", []):
                v = el.get("totalPageStatistics", {}).get("views", {}).get("allPageViews", {})
                row(el)["page_views"] = v.get("pageViews")
        except Exception as e:
            self.warn("page views", e)
        return list(rows.values())

    def posts(self):
        try:
            els = self.call(f"posts?author={self.enc}&q=author&count=25&sortBy=LAST_MODIFIED").get("elements", [])
        except Exception as e:
            self.warn("post list", e); return []
        els = [e for e in els if e.get("lifecycleState", "PUBLISHED") == "PUBLISHED" and e.get("publishedAt")]
        stats = {}
        shares = [e["id"] for e in els if ":share:" in e["id"]]
        ugcs = [e["id"] for e in els if ":ugcPost:" in e["id"]]
        q = lambda ids: ",".join(urllib.parse.quote(i, safe="") for i in ids)
        try:
            path = f"organizationalEntityShareStatistics?q=organizationalEntity&organizationalEntity={self.enc}"
            if shares: path += f"&shares=List({q(shares)})"
            if ugcs: path += f"&ugcPosts=List({q(ugcs)})"
            if shares or ugcs:
                for el in self.call(path).get("elements", []):
                    stats[el.get("share") or el.get("ugcPost")] = el.get("totalShareStatistics", {})
        except Exception as e:
            self.warn("per-post stats", e)
        out = []
        for e in els:
            s, t = stats.get(e["id"], {}), datetime.fromtimestamp(e["publishedAt"] / 1000, tz=timezone.utc)
            eng = sum(s.get(k) or 0 for k in ("clickCount", "likeCount", "commentCount", "shareCount")) if s else None
            out.append({"platform": "linkedin", "id": e["id"], "ts": t.isoformat(), "date": t.date().isoformat(), "type": "LI",
                        "text": li_text(e.get("commentary")), "url": f"https://www.linkedin.com/feed/update/{e['id']}/",
                        "thumb": None, "impressions": s.get("impressionCount"), "reach": s.get("uniqueImpressionsCount"),
                        "views": s.get("impressionCount"), "likes": s.get("likeCount"), "comments": s.get("commentCount"),
                        "reposts": s.get("shareCount"), "clicks": s.get("clickCount"), "interactions": eng})
        return out


# ---------- LinkedIn (manual fallback) ----------
# If the API isn't approved, numbers can be typed into manual/linkedin.csv instead.
def linkedin_manual(history):
    if not os.path.exists(MANUAL_LI):
        return
    history[:] = [h for h in history if not (h["platform"] == "linkedin" and h.get("src") == "manual")]
    n = 0
    with open(MANUAL_LI) as f:
        for r in csv.DictReader(f):
            if not r.get("date") or r["date"].strip().startswith("#"):
                continue
            def num(k):
                v = (r.get(k) or "").replace(",", "").strip()
                return int(v) if v.isdigit() else None
            merge(history, {"date": r["date"].strip(), "platform": "linkedin", "src": "manual", "followers": num("followers"),
                            "impressions": num("impressions"), "reach": num("members_reached"),
                            "engagements": num("engagements"), "page_views": num("page_views")})
            n += 1
    history.sort(key=lambda h: (h["date"], h["platform"]))
    if n:
        print(f"LinkedIn: {n} manual rows")


# ---------- demo data ----------
def demo():
    random.seed(11)
    history = []
    def split(total, weights):
        keys, out, left = list(weights), {}, total
        for k in keys[:-1]:
            out[k] = int(total * weights[k]); left -= out[k]
        out[keys[-1]] = max(left, 0)
        return out
    for i in range(BACKFILL_DAYS, 0, -1):
        d = TODAY - timedelta(days=i)
        spike = 2500 if i == 26 else 1150 if i == 16 else 300 if i in (2, 6) else 0
        base = random.randint(40, 260) + spike
        cross = {}
        for t, w in {"POST": .76, "STORY": .21, "REEL": .03}.items():
            fol = random.uniform(.62, .8)
            cross[f"FOLLOWER|{t}"] = int(base * w * fol)
            cross[f"NON_FOLLOWER|{t}"] = int(base * w * (1 - fol))
        views = sum(cross.values())
        likes, comments, shares = random.randint(1, 12) + spike // 90, random.randint(0, 2), random.randint(0, 3) + spike // 800
        saves, reposts = random.randint(0, 2), random.randint(0, 1)
        tw = {"POST": .82, "STORY": .12, "REEL": .06}
        history.append({
            "date": d.isoformat(), "platform": "instagram", "views": views,
            "views_cross": cross, "views_by_follow": regroup(cross, 0), "views_by_type": regroup(cross, 1),
            "reach": int(views * random.uniform(.2, .35)), "profile_views": random.randint(3, 25) + spike // 100,
            "likes": likes, "comments": comments, "shares": shares, "saves": saves, "reposts": reposts,
            "likes_by_type": split(likes, tw), "comments_by_type": split(comments, tw), "shares_by_type": split(shares, tw),
            "saves_by_type": split(saves, tw), "reposts_by_type": split(reposts, tw),
            "interactions": likes + comments + shares + saves + reposts,
            "interactions_by_type": split(likes + comments + shares + saves + reposts, tw),
            "follows": random.randint(0, 3) + (11 if i == 26 else 0), "unfollows": random.randint(0, 1)})
    history.append({"date": TODAY.isoformat(), "platform": "instagram", "followers": 808})
    fill_followers(history)
    for i in range(BACKFILL_DAYS, 0, -1):
        d = TODAY - timedelta(days=i)
        post_day = i % 5 == 1
        imp = random.randint(20, 120) + (random.randint(400, 1400) if post_day else 0)
        likes, com, sh, cl = imp // 40 + random.randint(0, 3), random.randint(0, 2), random.randint(0, 1), imp // 30
        history.append({"date": d.isoformat(), "platform": "linkedin", "src": "api", "impressions": imp,
                        "reach": int(imp * .7), "likes": likes, "comments": com, "shares": sh, "clicks": cl,
                        "engagements": likes + com + sh + cl, "follows": random.randint(0, 3), "page_views": random.randint(5, 40)})
    history.append({"date": TODAY.isoformat(), "platform": "linkedin", "src": "api", "followers": 1240})
    fill_followers(history, "linkedin")
    history.sort(key=lambda h: (h["date"], h["platform"]))

    samples = [("REELS", "STEM education hot takes 🔥", 699, 18, 0, 6, 0), ("STORY", "", 238, 3, 0, 0, 0),
               ("FEED", "Happy Week 12!", 181, 8, 0, 0, 1), ("FEED", "Happy Week 11!", 315, 12, 0, 0, 0),
               ("FEED", "Alumni outcomes: meet a CalTeach grad now teaching in LA", 2800, 26, 0, 3, 2),
               ("STORY", "", 97, 1, 0, 0, 0), ("STORY", "", 94, 1, 0, 0, 0), ("STORY", "", 105, 1, 0, 0, 0),
               ("FEED", "Info session this Thursday, come meet the team", 420, 15, 2, 1, 0),
               ("FEED", "Thank you to our partner schools", 260, 11, 1, 0, 0),
               ("REELS", "A day in a CalTeach practicum", 274, 9, 1, 2, 0),
               ("FEED", "Fellowship applications are open", 1230, 22, 3, 4, 1)]
    gaps = [2, 2, 10, 10, 12, 15, 15, 15, 19, 23, 27, 33]
    posts = []
    for n, ((kind, cap, views, likes, com, shares, rep), g) in enumerate(zip(samples, gaps)):
        dt = datetime.now(timezone.utc) - timedelta(days=g, hours=n)
        posts.append({"platform": "instagram", "id": f"demo{n}", "ts": dt.isoformat(), "date": dt.date().isoformat(),
                      "type": kind, "text": cap, "url": None, "thumb": None, "views": views,
                      "reach": int(views * .55), "likes": likes if kind != "STORY" else None, "comments": com if kind != "STORY" else None,
                      "shares": shares, "saves": random.randint(0, 5) if kind != "STORY" else None,
                      "reposts": rep if kind != "STORY" else None, "replies": 0 if kind == "STORY" else None,
                      "interactions": likes + com + shares + rep})
    for n, (cap, g) in enumerate([("Applications for our spring STEM teaching courses are open", 3),
                                  ("Congratulations to this year's graduating CalTeach cohort", 9),
                                  ("Info session recap and slides", 14), ("We're hiring student ambassadors", 21)]):
        imp = random.randint(500, 2400); dt = datetime.now(timezone.utc) - timedelta(days=g)
        lk, cm, rp, ck = imp // 35, random.randint(0, 6), random.randint(0, 4), imp // 25
        posts.append({"platform": "linkedin", "id": f"li{n}", "ts": dt.isoformat(), "date": dt.date().isoformat(), "type": "LI",
                      "text": cap, "url": None, "thumb": None, "impressions": imp, "views": imp, "reach": int(imp * .7),
                      "likes": lk, "comments": cm, "reposts": rp, "clicks": ck, "interactions": lk + cm + rp + ck})
    ages = {"13-17": .002, "18-24": .359, "25-34": .326, "35-44": .122, "45-54": .122, "55-64": .05, "65+": .019}
    ag = {}
    for a, s in ages.items():
        ag[f"{a}|F"], ag[f"{a}|M"] = round(808 * s * .623), round(808 * s * .377)
    audience = {"age_gender": ag, "city": {"Berkeley, California": 212, "Oakland, California": 74,
                "San Francisco, California": 61, "Los Angeles, California": 38, "San Jose, California": 27}}
    meta = {"updated": datetime.now(timezone.utc).isoformat(), "demo": True,
            "account": {"username": "calteachberkeley", "followers": 808, "picture": None},
            "periods": {"7": {"reach": 410, "prev_reach": 352}, "30": {"reach": 1535, "prev_reach": 685}}, "errors": []}
    return history, posts, audience, meta


# ---------- main ----------
def main():
    if "--demo" in sys.argv:
        h, p, a, m = demo()
        save(HISTORY, h); save(POSTS, p); save(AUDIENCE, a); save(META, m)
        print("Wrote demo data.")
        return

    history, old_posts = load(HISTORY, []), load(POSTS, [])
    old_meta = load(META, {})
    if old_meta.get("demo"):
        history, old_posts, old_meta = [], [], {}   # first real run: drop the sample data
    meta = {"updated": datetime.now(timezone.utc).isoformat(), "demo": False, "errors": [],
            "account": old_meta.get("account"), "periods": old_meta.get("periods", {})}
    audience = load(AUDIENCE, {}) if not old_meta.get("demo") else {}
    posts = old_posts

    uid, tok = os.environ.get("IG_USER_ID"), os.environ.get("IG_ACCESS_TOKEN")
    if uid and tok:
        ig = Instagram(uid, tok)
        try:
            acct = ig.account()
            meta["account"] = {"username": acct.get("username"), "followers": acct.get("followers_count"),
                               "picture": acct.get("profile_picture_url")}
            merge(history, {"date": TODAY.isoformat(), "platform": "instagram",
                            "followers": acct.get("followers_count"), "posts_total": acct.get("media_count")})
            have = {h["date"] for h in history if h["platform"] == "instagram" and "views" in h}
            filled = 0
            for i in range(1, BACKFILL_DAYS + 1):
                d = TODAY - timedelta(days=i)
                if i > 3 and d.isoformat() in have:      # recent days get refreshed, older ones are final
                    continue
                row = ig.day(d)
                if i > 3 and not any(row.get(k) is not None for k in ("views", "reach", "likes")):
                    break                                 # API has no data this far back
                merge(history, row); filled += 1
            fill_followers(history)
            for n in (7, 30):
                meta["periods"][str(n)] = {"reach": ig.period_reach(n), "prev_reach": ig.period_reach(n, n)}
            audience = ig.audience() or audience
            fresh = ig.posts() + ig.stories()
            ids = {p["id"] for p in fresh}
            cutoff = (TODAY - timedelta(days=180)).isoformat()
            posts = fresh + [p for p in old_posts if p["id"] not in ids and (p["platform"] == "linkedin" or
                             (p.get("type") == "STORY" and p["date"] >= cutoff))]
            print(f"Instagram: @{acct.get('username')} {acct.get('followers_count')} followers, "
                  f"{filled} days updated, {len(fresh)} posts/stories")
        except Exception as e:
            meta["errors"].append(f"Instagram: {e}")
    else:
        print("Instagram: skipped (IG_USER_ID / IG_ACCESS_TOKEN not set)")

    org, ltok = os.environ.get("LI_ORG_ID"), os.environ.get("LI_ACCESS_TOKEN")
    if org and ltok:
        L = LinkedIn(org, ltok)
        try:
            n = L.followers()
            merge(history, {"date": TODAY.isoformat(), "platform": "linkedin", "src": "api", "followers": n})
            for r in L.daily(TODAY - timedelta(days=BACKFILL_DAYS), TODAY):
                merge(history, r)
            fill_followers(history, "linkedin")
            lp = L.posts()
            if lp:
                posts = [p for p in posts if p["platform"] != "linkedin"] + lp
            print(f"LinkedIn: {n} followers, {len(lp)} posts (API version {L.version})")
        except Exception as e:
            meta["errors"].append(f"LinkedIn: {e}")
    else:
        print("LinkedIn API: skipped (LI_ORG_ID / LI_ACCESS_TOKEN not set)")
    try:
        linkedin_manual(history)
    except Exception as e:
        meta["errors"].append(f"LinkedIn file: {e}")

    posts.sort(key=lambda p: p.get("ts") or p["date"], reverse=True)
    save(HISTORY, history); save(POSTS, posts); save(AUDIENCE, audience); save(META, meta)
    for e in meta["errors"]:
        print("ERROR", e, file=sys.stderr)
    if meta["errors"]:
        sys.exit(1)   # data is saved; this turns the GitHub Action red so someone notices (e.g. revoked token)


if __name__ == "__main__":
    main()
