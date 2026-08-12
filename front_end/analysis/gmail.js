// helpers
const notNull = (v) => v !== null && v !== undefined && v !== "";
const scopedTo = (rows, compId) => rows.filter((r) => r.id === compId);

function response(rows, compId) {
  if (!rows || rows.length === 0) return "empty analytics";
  return rows
    .filter((r) => notNull(r.return_time) && notNull(r.email) && r.id === compId)
    .map((r) => ({ email: r.email, send_time: r.send_time }));
}

function conversion(rows, compId) {
  if (!rows || rows.length === 0) return "empty analytics";
  const scoped = scopedTo(rows, compId);
  const sends = scoped.filter((r) => notNull(r.send_time)).length;
  const returns = scoped.filter((r) => notNull(r.return_time)).length;
  if (sends === 0) return "no sends to compute conversion rate";
  const rate = returns / sends;
  return `conversion rate ${rate} and the percentage is ${rate * 100}`;
}

function avgResponseTime(rows, compId) {
  if (!rows || rows.length === 0) return "empty analytics";
  const replied = scopedTo(rows, compId).filter(
    (r) => notNull(r.return_time) && notNull(r.send_time)
  );
  if (replied.length === 0) return "no replies to compute response time";
  const deltasMs = replied.map(
    (r) => new Date(r.return_time) - new Date(r.send_time)
  );
  const meanMs = deltasMs.reduce((a, b) => a + b, 0) / deltasMs.length;
  return `avg response time: ${meanMs} ms`; // format as needed (e.g. via a duration lib)
}

function quantile(sortedArr, q) {
  const pos = (sortedArr.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  if (sortedArr[base + 1] !== undefined) {
    return sortedArr[base] + rest * (sortedArr[base + 1] - sortedArr[base]);
  }
  return sortedArr[base];
}

function responseTimeDistribution(rows, compId) {
  if (!rows || rows.length === 0) return "empty analytics";
  const replied = scopedTo(rows, compId).filter(
    (r) => notNull(r.return_time) && notNull(r.send_time)
  );
  if (replied.length === 0) return "no replies to compute response time distribution";
  const deltasMs = replied
    .map((r) => new Date(r.return_time) - new Date(r.send_time))
    .sort((a, b) => a - b);
  const mean = deltasMs.reduce((a, b) => a + b, 0) / deltasMs.length;
  return {
    p50: quantile(deltasMs, 0.5),
    p90: quantile(deltasMs, 0.9),
    mean,
    max: deltasMs[deltasMs.length - 1],
  };
}

// freq: "day" | "hour" (extend as needed)
function bucketKey(date, freq) {
  const d = new Date(date);
  if (freq === "hour") {
    return d.toISOString().slice(0, 13); // YYYY-MM-DDTHH
  }
  return d.toISOString().slice(0, 10); // YYYY-MM-DD
}

function sendsByPeriod(rows, compId, freq = "day") {
  if (!rows || rows.length === 0) return "empty analytics";
  const sent = scopedTo(rows, compId).filter((r) => notNull(r.send_time));
  const buckets = {};
  for (const r of sent) {
    const key = bucketKey(r.send_time, freq);
    buckets[key] = (buckets[key] || 0) + 1;
  }
  return buckets;
}

function funnelByPeriod(rows, compId, freq = "day") {
  if (!rows || rows.length === 0) return "empty analytics";
  const scoped = scopedTo(rows, compId);
  const sendBuckets = {};
  const returnBuckets = {};

  for (const r of scoped) {
    if (notNull(r.send_time)) {
      const key = bucketKey(r.send_time, freq);
      sendBuckets[key] = (sendBuckets[key] || 0) + 1;
    }
    if (notNull(r.return_time)) {
      // bucketed by send_time, matching the pandas version's Grouper(key="send_time")
      const key = bucketKey(r.send_time, freq);
      returnBuckets[key] = (returnBuckets[key] || 0) + 1;
    }
  }

  const allKeys = new Set([...Object.keys(sendBuckets), ...Object.keys(returnBuckets)]);
  const out = {};
  for (const key of allKeys) {
    const sends = sendBuckets[key] || 0;
    const returns = returnBuckets[key] || 0;
    out[key] = {
      sends,
      returns,
      conversion_rate: sends === 0 ? null : returns / sends,
    };
  }
  return out;
}

function topRepliers(rows, compId, n = 10) {
  if (!rows || rows.length === 0) return "empty analytics";
  const replied = scopedTo(rows, compId).filter(
    (r) => notNull(r.return_time) && notNull(r.email)
  );
  const counts = {};
  for (const r of replied) {
    counts[r.email] = (counts[r.email] || 0) + 1;
  }
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([email, count]) => ({ email, count }));
}

function nonResponders(rows, compId) {
  if (!rows || rows.length === 0) return "empty analytics";
  const scoped = scopedTo(rows, compId);
  const sentEmails = new Set(
    scoped.filter((r) => notNull(r.send_time) && notNull(r.email)).map((r) => r.email)
  );
  const repliedEmails = new Set(
    scoped.filter((r) => notNull(r.return_time) && notNull(r.email)).map((r) => r.email)
  );
  return [...sentEmails].filter((e) => !repliedEmails.has(e)).sort();
}

function bounceRate(rows, compId) {
  if (!rows || rows.length === 0) return "empty analytics";
  if (!rows.some((r) => "bounced" in r)) return "no bounce data available";
  const scoped = scopedTo(rows, compId);
  const sent = scoped.filter((r) => notNull(r.send_time)).length;
  const bounced = scoped.filter((r) => r.bounced === true).length;
  if (sent === 0) return "no sends to compute bounce rate";
  const rate = bounced / sent;
  return `bounce rate ${rate} and the percentage is ${rate * 100}`;
}

function summary(rows, compId) {
  if (!rows || rows.length === 0) return { error: "empty analytics" };
  const scoped = scopedTo(rows, compId);
  const sends = scoped.filter((r) => notNull(r.send_time)).length;
  const returns = scoped.filter((r) => notNull(r.return_time)).length;
  return {
    total_sends: sends,
    total_returns: returns,
    conversion_rate: sends ? returns / sends : null,
    reason: sends ? null : "no sends",
  };
}