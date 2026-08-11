// rows: array of { id, number, sent_time, recieve_time }
const notNull = (v) => v !== null && v !== undefined && v !== "";
const scopedTo = (rows, compId) => rows.filter((r) => r.id === compId);

function conversion(rows, compId) {
  if (!rows || rows.length === 0) return "empty analytics";
  const scoped = scopedTo(rows, compId);
  const sends = scoped.filter((r) => notNull(r.sent_time)).length;
  if (sends === 0) return "no sends to compute conversion rate";
  const receives = scoped.filter((r) => notNull(r.recieve_time)).length;
  const rate = receives / sends;
  return `the conversion rate is the ${rate} and the percentage is the ${rate * 100}`;
}

function bouncedRate(rows, compId) {
  if (!rows || rows.length === 0) return "empty analytics";
  const scoped = scopedTo(rows, compId);
  const sends = scoped.filter((r) => notNull(r.sent_time)).length;
  if (sends === 0) return "no sends to compute bounced rate";
  const receives = scoped.filter((r) => notNull(r.recieve_time)).length;
  const bounced = sends - receives;
  const rate = bounced / sends;
  return `the bounced rate is the ${rate} and the percentage is the ${rate * 100}`;
}

function topRepliers(rows, compId, n = 10) {
  if (!rows || rows.length === 0) return "empty analytics";
  const replied = scopedTo(rows, compId).filter(
    (r) => notNull(r.recieve_time) && notNull(r.number)
  );
  const counts = {};
  for (const r of replied) {
    counts[r.number] = (counts[r.number] || 0) + 1;
  }
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([number, count]) => ({ number, count }));
}

function avgResponseTime(rows, compId) {
  if (!rows || rows.length === 0) return "empty analytics";
  const replied = scopedTo(rows, compId).filter(
    (r) => notNull(r.recieve_time) && notNull(r.sent_time)
  );
  if (replied.length === 0) return "no replies to compute response time";
  const deltasMs = replied.map(
    (r) => new Date(r.recieve_time) - new Date(r.sent_time)
  );
  const meanMs = deltasMs.reduce((a, b) => a + b, 0) / deltasMs.length;
  return `avg response time: ${meanMs} ms`; // format with a duration lib if you want h/m/s
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
    (r) => notNull(r.recieve_time) && notNull(r.sent_time)
  );
  if (replied.length === 0) return "no replies to compute response time distribution";
  const deltasMs = replied
    .map((r) => new Date(r.recieve_time) - new Date(r.sent_time))
    .sort((a, b) => a - b);
  const mean = deltasMs.reduce((a, b) => a + b, 0) / deltasMs.length;
  return {
    p50: quantile(deltasMs, 0.5),
    p90: quantile(deltasMs, 0.9),
    mean,
    max: deltasMs[deltasMs.length - 1],
  };
}

function bucketKey(date, freq) {
  const d = new Date(date);
  if (freq === "hour") return d.toISOString().slice(0, 13);
  return d.toISOString().slice(0, 10); // "day" default
}

function sendsByPeriod(rows, compId, freq = "day") {
  if (!rows || rows.length === 0) return "empty analytics";
  const sent = scopedTo(rows, compId).filter((r) => notNull(r.sent_time));
  const buckets = {};
  for (const r of sent) {
    const key = bucketKey(r.sent_time, freq);
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
    if (notNull(r.sent_time)) {
      const key = bucketKey(r.sent_time, freq);
      sendBuckets[key] = (sendBuckets[key] || 0) + 1;
    }
    if (notNull(r.recieve_time)) {
      // bucketed by sent_time, matching the pandas Grouper(key="sent_time")
      const key = bucketKey(r.sent_time, freq);
      returnBuckets[key] = (returnBuckets[key] || 0) + 1;
    }
  }

  const allKeys = new Set([...Object.keys(sendBuckets), ...Object.keys(returnBuckets)]);
  const out = {};
  for (const key of allKeys) {
    const sends = sendBuckets[key] || 0;
    const returns = returnBuckets[key] || 0;
    out[key] = { sends, returns, conversion_rate: sends === 0 ? null : returns / sends };
  }
  return out;
}

function nonResponders(rows, compId) {
  if (!rows || rows.length === 0) return "empty analytics";
  const scoped = scopedTo(rows, compId);
  const sentNumbers = new Set(
    scoped.filter((r) => notNull(r.sent_time) && notNull(r.number)).map((r) => r.number)
  );
  const repliedNumbers = new Set(
    scoped.filter((r) => notNull(r.recieve_time) && notNull(r.number)).map((r) => r.number)
  );
  return [...sentNumbers].filter((n) => !repliedNumbers.has(n)).sort();
}

function summary(rows, compId) {
  if (!rows || rows.length === 0) return { error: "empty analytics" };
  const scoped = scopedTo(rows, compId);
  const sends = scoped.filter((r) => notNull(r.sent_time)).length;
  const returns = scoped.filter((r) => notNull(r.recieve_time)).length;
  return {
    total_sends: sends,
    total_returns: returns,
    conversion_rate: sends ? returns / sends : null,
    reason: sends ? null : "no sends",
  };
}