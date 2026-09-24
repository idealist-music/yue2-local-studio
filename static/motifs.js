"use strict";
(() => {
  const $ = id => document.getElementById(id);
  let current = null;
  const key = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, "0")).join("");
  const show = message => { $("motif-error").textContent = message; $("motif-error").hidden = !message; };
  const setStatus = message => { $("motif-status").textContent = message; };
  async function json(path, options = {}) {
    const response = await fetch(path, {cache: "no-store", ...options, headers: {"Content-Type": "application/json", ...(options.headers || {})}});
    const data = await response.json();
    if (!response.ok) throw new Error(Array.isArray(data.detail) ? data.detail.map(x => x.msg).join(" / ") : data.detail || `HTTP ${response.status}`);
    return data;
  }
  function update() {
    const ready = !!current;
    $("motif-clip").disabled = !ready;
    $("motif-transcribe").disabled = !ready || current.stage?.clip?.status !== "completed";
    $("motif-plan").disabled = !ready || current.stage?.transcribe?.status !== "awaiting_review";
    $("motif-prepare").disabled = !ready || current.stage?.plan?.status !== "awaiting_review";
    $("motif-generate").disabled = !ready || current.review?.status !== "reviewed";
    if (ready) {
      $("motif-style").value = current.conditions.style || "";
      $("motif-lyrics").value = current.conditions.lyrics || "";
      $("motif-title").value = current.conditions.title || "";
      $("motif-start").value = current.conditions.start;
      $("motif-end").value = current.conditions.end;
      $("motif-seed").value = current.conditions.seed || "0";
      const f = current.files || {};
      if (f.motif) { $("motif-abc").value = "採譜ABC: " + f.motif; }
      if (current.stage?.plan?.analysis) $("motif-analysis").textContent = JSON.stringify(current.stage.plan.analysis, null, 2);
    }
  }
  async function load(id) { current = await json(`/api/motifs/${id}`); update(); }
  async function save() {
    if (!current) return;
    const body = {expected_revision: current.revision, start: Number($("motif-start").value), end: Number($("motif-end").value), style: $("motif-style").value, lyrics: $("motif-lyrics").value, seed: $("motif-seed").value, purpose: $("motif-purpose").value, sections: [$("motif-section").value[0].toUpperCase() + $("motif-section").value.slice(1)], transform: {}};
    body.title = $("motif-title").value;
    current = await json(`/api/motifs/${current.id}`, {method: "PUT", body: JSON.stringify(body)});
    update();
  }
  async function stage(name) {
    if (!current) return;
    const result = await json(`/api/motifs/${current.id}/${name}`, {method: "POST", body: JSON.stringify({expected_revision: current.revision, submission_key: key()})});
    current = result.project; setStatus(`${name} をキューに登録しました`); update();
    const timer = setInterval(async () => { try { await load(current.id); if (current.stage?.[name === "clip" ? "clip" : name]?.status === "completed" || current.stage?.[name === "transcribe" ? "transcribe" : name]?.status === "awaiting_review") clearInterval(timer); } catch { clearInterval(timer); } }, 1500);
  }
  $("motif-open").addEventListener("click", async () => {
    $("motif-dialog").showModal(); show("");
    try {
      const jobs = await json("/api/jobs");
      $("motif-source").replaceChildren(new Option("元曲を選択…", ""), ...jobs.jobs.filter(j => j.files?.flac || j.files?.wav).map(j => new Option(j.title || "無題", j.id)));
    } catch (e) { show(e.message); }
  });
  $("motif-close").addEventListener("click", () => $("motif-dialog").close());
  $("motif-source").addEventListener("change", async e => {
    if (!e.target.value) return;
    try { current = await json("/api/motifs/from-song", {method: "POST", body: JSON.stringify({source_job_id: e.target.value, submission_key: key()})}); update(); setStatus("元音源を選択しました"); }
    catch (err) { show(err.message); }
  });
  $("motif-upload").addEventListener("change", async e => {
    const file = e.target.files[0]; if (!file) return;
    try {
      const response = await fetch(`/api/motifs/upload?filename=${encodeURIComponent(file.name)}&submission_key=${key()}`, {method: "POST", headers: {"Content-Type": "application/octet-stream"}, body: file});
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || "アップロードに失敗しました");
      current = data; update(); setStatus("音源を保存しました。条件を入力してください");
    } catch (err) { show(err.message); }
  });
  $("motif-save").addEventListener("click", async () => { try { await save(); setStatus("条件を保存しました"); } catch (e) { show(e.message); } });
  $("motif-clip").addEventListener("click", async () => { try { await save(); await stage("clip"); } catch (e) { show(e.message); } });
  $("motif-transcribe").addEventListener("click", async () => { try { await stage("transcribe"); } catch (e) { show(e.message); } });
  $("motif-plan").addEventListener("click", async () => { try { await stage("plan"); } catch (e) { show(e.message); } });
  $("motif-prepare").addEventListener("click", async () => { try { current = await json(`/api/motifs/${current.id}/prepare`, {method: "POST", body: JSON.stringify({expected_revision: current.revision, section: $("motif-section").value, voice: $("motif-purpose").value, seed: $("motif-seed").value, transform: {}})}); $("motif-manifest").textContent = "モチーフを組み込みました。ABCを確認して生成できます。"; update(); } catch (e) { show(e.message); } });
  $("motif-generate").addEventListener("click", async () => {
    try {
      const edited = await (await fetch(current.files.edited)).text();
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(edited));
      const sha = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
      current = await json(`/api/motifs/${current.id}/review`, {method: "POST", body: JSON.stringify({expected_revision: current.revision, confirmation: true, edited_sha256: sha, warnings_acknowledged: true})});
      current = (await json(`/api/motifs/${current.id}/generate`, {method: "POST", body: JSON.stringify({expected_revision: current.revision, submission_key: key()})})).project;
      setStatus("生成キューに登録しました"); update();
    } catch (e) { show(e.message); }
  });
})();
