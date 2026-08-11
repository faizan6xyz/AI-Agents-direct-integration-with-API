// ---------------------------------------------------------------------------
// Long-term (post) metrics schema:
// { id, views, reach, likes, comments, saved, shares, total_interactions,
//   profile_activity, follows, time }
// ---------------------------------------------------------------------------

function isEmpty(data) {
  return data == null || data.length === 0;
}

// groupBy(data, keyFn) -> Map<key, rows[]>
function groupBy(data, keyFn) {
  const map = new Map();
  for (const row of data) {
    const key = keyFn(row);
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(row);
  }
  return map;
}

function mean(rows, field) {
  const vals = rows.map(r => r[field]).filter(v => v != null && !Number.isNaN(v));
  if (vals.length === 0) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function sum(rows, field) {
  return rows.reduce((acc, r) => acc + (r[field] ?? 0), 0);
}

// Step 1 (compulsory, always first): per-post averages + rate metrics.
// month/year are attached PER ROW before aggregation, then carried through
// as the month/year of the post's most recent snapshot.
function conversion(data) {
  if (isEmpty(data)) return "empty analytics";

  const withDate = data.map(r => {
    const d = new Date(r.time);
    return { ...r, _month: d.getMonth() + 1, _year: d.getFullYear() };
  });

  const grouped = groupBy(withDate, r => r.id);
  const result = [];

  for (const [id, rows] of grouped) {
    const views = mean(rows, "views");
    const likes = mean(rows, "likes");
    const comments = mean(rows, "comments");
    const shares = mean(rows, "shares");
    const totalInteractions = mean(rows, "total_interactions");
    const follows = mean(rows, "follows");
    const reach = mean(rows, "reach");

    // most recent snapshot's month/year for this post
    const latest = rows.reduce((a, b) => (new Date(a.time) > new Date(b.time) ? a : b));

    result.push({
      id,
      views,
      likes,
      comments,
      shares,
      reach,
      total_interactions: totalInteractions,
      follows,
      comment_rate: views ? comments / views : null,
      like_rate: views ? likes / views : null,
      share_rate: views ? shares / views : null,
      visit: totalInteractions != null && follows != null ? totalInteractions - follows : null,
      month: latest._month,
      year: latest._year,
    });
  }
  return result;
}

// Trend functions need RAW (non-averaged) rows, not the conversion() output,
// since conversion() collapses each post to a single row per month.
function growthOverTimeByMonth(rawData) {
  if (isEmpty(rawData)) return "empty analytics";
  const withMonth = rawData.map(r => ({ ...r, _month: new Date(r.time).getMonth() + 1 }));
  const grouped = groupBy(withMonth, r => r._month);
  return [...grouped.entries()]
    .map(([month, rows]) => ({ month, total_interactions: sum(rows, "total_interactions") }))
    .sort((a, b) => a.month - b.month);
}

function growthOverTimeByYear(rawData) {
  if (isEmpty(rawData)) return "empty analytics";
  const withYear = rawData.map(r => ({ ...r, _year: new Date(r.time).getFullYear() }));
  const grouped = groupBy(withYear, r => r._year);
  return [...grouped.entries()]
    .map(([year, rows]) => ({ year, total_interactions: sum(rows, "total_interactions") }))
    .sort((a, b) => a.year - b.year);
}

function topPosts(data, metric = "views", n = 10) {
  if (isEmpty(data)) return "empty analytics";
  return [...data].sort((a, b) => (b[metric] ?? 0) - (a[metric] ?? 0)).slice(0, n);
}

// These read from conversion()'s output (per-post aggregated rows).
function viralityScore(conversionData) {
  if (isEmpty(conversionData)) return "empty analytics";
  return [...conversionData]
    .map(r => ({ id: r.id, share_rate: r.share_rate }))
    .sort((a, b) => (b.share_rate ?? -Infinity) - (a.share_rate ?? -Infinity));
}

function publicLoveScore(conversionData) {
  if (isEmpty(conversionData)) return "empty analytics";
  return [...conversionData]
    .map(r => ({ id: r.id, like_rate: r.like_rate }))
    .sort((a, b) => (b.like_rate ?? -Infinity) - (a.like_rate ?? -Infinity));
}

function publicEngagement(conversionData) {
  if (isEmpty(conversionData)) return "empty analytics";
  return [...conversionData]
    .map(r => ({ id: r.id, comment_rate: r.comment_rate }))
    .sort((a, b) => (b.comment_rate ?? -Infinity) - (a.comment_rate ?? -Infinity));
}

function followerGain(conversionData) {
  if (isEmpty(conversionData)) return "empty analytics";
  return [...conversionData].sort((a, b) => (b.follows ?? -Infinity) - (a.follows ?? -Infinity));
}

function profileVisits(conversionData) {
  if (isEmpty(conversionData)) return "empty analytics";
  return [...conversionData].sort((a, b) => (b.visit ?? -Infinity) - (a.visit ?? -Infinity));
}

function newReach(conversionData) {
  if (isEmpty(conversionData)) return "empty analytics";
  return [...conversionData].sort((a, b) => (b.reach ?? -Infinity) - (a.reach ?? -Infinity));
}

// Month-over-month growth needs RAW rows (not per-post-averaged),
// bucketed by year+month, summing raw engagement columns then computing
// the % change from the previous period.
function monthOverMonthGrowth(rawData) {
  if (isEmpty(rawData)) return "empty analytics";
  const withDate = rawData.map(r => {
    const d = new Date(r.time);
    return { ...r, _year: d.getFullYear(), _month: d.getMonth() + 1 };
  });
  const grouped = groupBy(withDate, r => `${r._year}-${String(r._month).padStart(2, "0")}`);

  const monthly = [...grouped.entries()]
    .map(([key, rows]) => {
      const [year, month] = key.split("-").map(Number);
      const totalEngagement = sum(rows, "likes") + sum(rows, "comments") + sum(rows, "shares");
      return { year, month, total_engagement: totalEngagement };
    })
    .sort((a, b) => (a.year - b.year) || (a.month - b.month));

  for (let i = 0; i < monthly.length; i++) {
    if (i === 0) {
      monthly[i].mom_growth = null;
    } else {
      const prev = monthly[i - 1].total_engagement;
      monthly[i].mom_growth = prev ? ((monthly[i].total_engagement - prev) / prev) * 100 : null;
    }
  }
  return monthly;
}

// Step 2: filter by post ids
function filtering(data, ids = null) {
  if (isEmpty(data)) return data;
  if (ids == null) return data;

  let numericIds;
  try {
    numericIds = ids.map(i => {
      const n = Number(i);
      if (Number.isNaN(n)) throw new Error("bad id");
      return n;
    });
  } catch {
    return [];
  }
  const idSet = new Set(numericIds);
  return data.filter(r => idSet.has(Number(r.id)));
}

// ---------------------------------------------------------------------------
// Short-term (story) metrics schema, 24h window:
// { id, views, likes, reach, replies, shares, navigation, profile_activity,
//   hour, follows }
// most comments for a story live in "replies"
// ---------------------------------------------------------------------------

function bestPostingHour(rawData) {
  if (isEmpty(rawData)) return "empty analytics";
  const withEngagement = rawData.map(r => ({
    ...r,
    total_engagement: (r.likes ?? 0) + (r.replies ?? 0) + (r.shares ?? 0),
  }));
  const grouped = groupBy(withEngagement, r => r.hour);
  return [...grouped.entries()]
    .map(([hour, rows]) => ({ hour, avg_engagement: mean(rows, "total_engagement") }))
    .sort((a, b) => (b.avg_engagement ?? -Infinity) - (a.avg_engagement ?? -Infinity));
}

function conversionStories(data) {
  if (isEmpty(data)) return "empty analytics";
  const grouped = groupBy(data, r => r.id);
  const result = [];
  for (const [id, rows] of grouped) {
    const views = mean(rows, "views");
    const likes = mean(rows, "likes");
    const replies = mean(rows, "replies");
    const shares = mean(rows, "shares");
    const reach = mean(rows, "reach");
    const follows = mean(rows, "follows");

    result.push({
      id,
      views,
      likes,
      replies,
      shares,
      reach,
      follows,
      comment_rate: views ? replies / views : null,
      like_rate: views ? likes / views : null,
      share_rate: views ? shares / views : null,
    });
  }
  return result;
}

// virality_score, public_engagement, public_love_score, follower_gain,
// new_reach all work identically for stories — just call them with
// conversionStories(data) output instead of conversion(data) output.

export {
  conversion,
  growthOverTimeByMonth,
  growthOverTimeByYear,
  topPosts,
  viralityScore,
  publicLoveScore,
  publicEngagement,
  followerGain,
  profileVisits,
  newReach,
  monthOverMonthGrowth,
  filtering,
  bestPostingHour,
  conversionStories,
};