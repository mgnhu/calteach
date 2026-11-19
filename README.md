# CalTeach Social Dashboard: setup guide

This gives your supervisor **one link** that shows how @calteachberkeley on Instagram and the CalTeach Berkeley LinkedIn page are doing: followers, reach, engagement, and which posts did best. Both update by themselves every morning once connected.

It costs nothing. GitHub runs the daily update and hosts the page.

> 🔒 **Never give anyone the Instagram or LinkedIn password, and never put it in this project.** You log in yourself on Meta's site, and it hands the tracker a read-only "access key" for stats.

---

## Step 1: Put the project on GitHub (5 min)

1. Make a free account at <https://github.com> if you don't have one (a CalTeach email works best so it stays with the program).
2. Click **+ → New repository**. Name it `calteach-social` and set it to **Public**. Create it.
3. Click **uploading an existing file**. Drag in *everything inside* the `calteach-social-tracker` folder, including the hidden `.github` folder. On Mac, press ⌘⇧. in Finder to show hidden folders. Click **Commit changes**.
4. **Settings → Pages:** Source = *Deploy from a branch*, Branch = `main`, Folder = `/docs`. Click Save.
5. **Settings → Actions → General → Workflow permissions:** pick **Read and write permissions**. Click Save.

After a minute, your dashboard is live at:
**`https://<your-github-username>.github.io/calteach-social/`**
That's the link for your supervisor (or anyone else). Nobody needs to log in to view it. Until Instagram is connected it shows sample data with a yellow "sample data" banner.

## Step 2: Connect Instagram (about 20 min, one time)

**2a. Check the account type.** In the Instagram app on @calteachberkeley: *Settings → Account type and tools*. It must be **Professional (Business or Creator)**. Then link it to a **Facebook Page**: *Edit profile → Page → Connect*. If CalTeach has no Facebook Page, create a basic one. It can stay empty.

**2b. Make a Meta developer app.**
1. Go to <https://developers.facebook.com>, log in with the Facebook account that manages the Page, and choose **My Apps → Create App**.
2. Pick use case **Other**, then type **Business**, and name it "CalTeach Stats".

**2c. Get the two values the tracker needs.**
1. Open **Tools → Graph API Explorer**. Pick your app in the top right.
2. Under *Permissions*, add: `instagram_basic`, `instagram_manage_insights`, `pages_show_list`, `pages_read_engagement`. Click **Generate Access Token** and approve.
3. Click the ⓘ next to the token → **Open in Access Token Tool → Extend Access Token**. Copy the new long token and paste it back into the Explorer's token box.
4. In the request box, run:
   `me/accounts?fields=name,access_token,instagram_business_account`
5. In the result, find the CalTeach Page:
   - `instagram_business_account` → `id` is your **IG_USER_ID**
   - `access_token` is your **IG_ACCESS_TOKEN**. Because you extended the token first, this one doesn't expire.

**2d. Give them to GitHub (kept secret, never shown on the page).**
In your repo: **Settings → Secrets and variables → Actions → New repository secret**. Add both:
- Name `IG_USER_ID`, value = the id
- Name `IG_ACCESS_TOKEN`, value = the token

**2e. Test.** Go to **Actions → Collect social stats → Run workflow**. When it turns green ✅, refresh the dashboard. The sample data is gone, and real Instagram numbers and posts appear. It now runs automatically every morning.

## Step 3: Connect the LinkedIn page (linkedin.com/company/calteachberkeley)

**Option A: automatic (recommended).** This needs one approval from LinkedIn, done once. It's free, but LinkedIn reviews the request, which can take days to a few weeks. Whoever does this must be an **admin of the CalTeach LinkedIn page**, ideally using a berkeley.edu email.

1. Go to <https://www.linkedin.com/developers/apps> → **Create app**.
   - LinkedIn Page: `calteachberkeley`. Privacy policy URL: the CalTeach or UC Berkeley website. Upload any logo.
2. On the app's **Settings** tab, click **Verify** next to the Page and send the link to a page admin (or approve it yourself if you're one).
3. **Products** tab → **Community Management API** → **Request access**. Don't add any other product to this app, because LinkedIn requires this one to be alone.
   - Fill the form honestly: organization = UC Berkeley CalTeach, website = the berkeley.edu page, use case = *"Internal analytics dashboard for our own LinkedIn Page: reading page, follower and post statistics. No posting, no data shared outside our team."*
4. Once approved: go to **Docs and tools → OAuth Token Tools → Generate token**. Pick this app and check the scopes **`rw_organization_admin`** and **`r_organization_social`**. Log in and copy the token.
5. Find the page's number: open the page's admin view. The URL looks like `linkedin.com/company/12345678/admin/`. That number is the org ID.
6. Add two GitHub secrets (same place as Step 2d): **`LI_ORG_ID`** = that number, **`LI_ACCESS_TOKEN`** = the token.
7. **Run workflow** again. The LinkedIn tab switches to daily charts with impressions, unique impressions, likes, comments, reposts, clicks, new followers, page views, and a post list.

⚠️ **The LinkedIn token expires every 60 days.** Set a repeating calendar reminder to redo step 4 and paste the new token into the `LI_ACCESS_TOKEN` secret. When it expires, the dashboard shows a red "needs renewing" banner.

**Option B: by hand, while waiting for approval (~2 min/week).** Page admin view → **Analytics**, set to the last 7 days. In GitHub, edit `manual/linkedin.csv` and add a line:
```
2026-11-23,1240,2140,1300,96,24
```
That's **date, followers, impressions, unique impressions, engagements, page views**. Type numbers without commas, and leave a spot empty if you don't have it. Once Option A is set up you can stop doing this.

---

## What the supervisor sees
A dark, phone-friendly dashboard with five tabs. Every tab has a 7/14/30/90-day picker, and changes are shown "vs." the period before.
- **Home:** views (with a mini chart), followers, net followers, top 3 posts, LinkedIn snapshot
- **Performance:** tap a card (Views, Viewers, Follower views, Non-follower views, Interactions, Profile visits) to chart it, plus views by content type (followers vs non-followers) and interactions by content type (likes, comments, reposts, shares, saves)
- **Content:** every post, reel and story with its stats, sortable by views, viewers, likes, comments, shares, saves. Tap one to open it on Instagram.
- **Audience:** followers, net followers, follows, unfollows over time, plus followers' gender, age range and top cities
- **LinkedIn:** followers, impressions, unique impressions, engagements, clicks, new followers, page views, plus each post's stats
- The **share button** (top right) sends the link. The **ⓘ button** explains what each number means.

The first sync fills in the last ~60 days of Instagram stats, so the charts aren't empty on day one.

## Good to know
- Follower counts before the first sync are worked back from daily follows/unfollows, so they're close but not exact.
- Stories disappear after 24 hours, so the dashboard only has stories that were live during a daily sync (it runs every morning).
- The dashboard page is public to anyone with the link. It shows only stats, never the login info.
- If a run fails (e.g. someone removed the app's access), GitHub emails the repo owner and the dashboard shows a yellow warning. Usually the fix is redoing Step 2c–2d.
- Handing it off later: add the next social media person under **Settings → Collaborators**.

## Files (for the curious)
- `collect.py`: grabs the stats (`python collect.py --demo` makes sample data)
- `.github/workflows/collect.yml`: the daily schedule
- `docs/index.html`: the dashboard page
- `docs/data/`: the saved numbers
- `manual/linkedin.csv`: manual LinkedIn entries (only if the API isn't connected)
