const state = {
    cropFile: null,
    labelFile: null,
    lang: "en",
    diagnosisId: null,
};

const VERDICT_BADGE = {
    GENUINE: { cls: "genuine", icon: "✓", dot: "trust" },
    SUSPICIOUS: { cls: "suspicious", icon: "⚠", dot: "warning" },
    FORGED: { cls: "forged", icon: "✕", dot: "critical" },
    UNVERIFIABLE: { cls: "unverifiable", icon: "ⓘ", dot: "info" },
};

const STATUS_BADGE = {
    ok: { cls: "ok", icon: "✓", dot: "trust" },
    retake: { cls: "retake", icon: "⚠", dot: "warning" },
    out_of_scope: { cls: "unverifiable", icon: "ⓘ", dot: "info" },
    uncertain: { cls: "warning", icon: "⚠", dot: "warning" },
};

function clientId() {
    let value = localStorage.getItem("agroguard_client_id");
    if (!value) {
        value = crypto.randomUUID();
        localStorage.setItem("agroguard_client_id", value);
    }
    return value;
}

function navigate(screen) {
    document.querySelectorAll(".screen").forEach((item) => item.classList.remove("active"));
    const target = document.getElementById(screen);
    if (target) target.classList.add("active");
}

function setResultBadge(badgeClass, icon) {
    const badge = document.getElementById("resultBadge");
    badge.className = `result-badge ${badgeClass}`;
    badge.textContent = icon;
}

function setCategory(labelKey) {
    const el = document.getElementById("resultCategory");
    const txt = t(labelKey);
    if (txt) el.textContent = txt;
}

function setQuickInfo(labelKey, dotClass) {
    const dot = document.getElementById("quickInfoDot");
    const lbl = document.getElementById("quickInfoLabel");
    dot.className = "dot";
    if (dotClass) dot.style.background = `var(--ag-${dotClass})`;
    const txt = t(labelKey);
    if (txt) lbl.textContent = txt;
}

function clearQuickInfo() {
    document.getElementById("quickInfoDot").style.background = "var(--ag-secondary)";
    document.getElementById("quickInfoLabel").textContent = "";
}

function showError(containerId, message) {
    const old = document.getElementById(containerId);
    if (old) old.remove();
    const error = document.createElement("div");
    error.id = containerId;
    error.className = "error";
    error.textContent = message;
    document.querySelector(".screen.active .card").appendChild(error);
}

function previewImage(input, previewId, buttonId) {
    const file = input.files && input.files[0];
    if (!file) return;
    const preview = document.getElementById(previewId);
    preview.innerHTML = "";
    const image = document.createElement("img");
    image.alt = "Selected image preview";
    image.src = URL.createObjectURL(file);
    preview.appendChild(image);
    preview.classList.remove("hidden");
    document.getElementById(buttonId).classList.remove("hidden");
    return file;
}

function handleCropImage(input) {
    state.cropFile = previewImage(input, "cropPreview", "diagnoseBtn");
}

function handleLabelImage(input) {
    state.labelFile = previewImage(input, "labelPreview", "verifyLabelBtn");
}

async function submitDiagnosis() {
    if (!state.cropFile) return;
    const loading = document.getElementById("diagnoseLoading");
    const button = document.getElementById("diagnoseBtn");
    loading.classList.remove("hidden");
    button.disabled = true;
    document.querySelectorAll(".error").forEach((item) => item.remove());
    try {
        const form = new FormData();
        form.append("image", state.cropFile, state.cropFile.name);
        form.append("lang", state.lang);
        const response = await fetchWithTimeout("/diagnose", { method: "POST", body: form });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || t("errors.diagnosis"));
        state.diagnosisId = data.diagnosis_id;
        renderDiagnosis(data);
    } catch (error) {
        showError("diagnoseError", `${error.message}`);
    } finally {
        loading.classList.add("hidden");
        button.disabled = false;
        navigate("result");
    }
}

async function submitLabel() {
    if (!state.labelFile) return;
    const loading = document.getElementById("verifyLoading");
    const button = document.getElementById("verifyLabelBtn");
    loading.classList.remove("hidden");
    button.disabled = true;
    try {
        const form = new FormData();
        form.append("image", state.labelFile, state.labelFile.name);
        const response = await fetchWithTimeout("/verify-label", { method: "POST", body: form });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || t("errors.label"));
        renderProductResult(data);
    } catch (error) {
        showError("labelError", `${error.message}`);
    } finally {
        loading.classList.add("hidden");
        button.disabled = false;
        navigate("result");
    }
}

async function submitQrCode() {
    const code = document.getElementById("qrCodeInput").value.trim();
    if (!code) {
        showError("qrError", t("errors.qr"));
        return;
    }
    try {
        const body = { code, client_id: clientId() };
        if (state.diagnosisId) {
            body.diagnosis_id = state.diagnosisId;
        }
        const response = await fetchWithTimeout("/verify-code", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || t("errors.qr"));
        renderQrResult(data);
    } catch (error) {
        showError("qrError", error.message);
    }
    navigate("result");
}

async function decodeQrImage(input) {
    const file = input.files && input.files[0];
    if (!file) return;
    try {
        const form = new FormData();
        form.append("image", file, file.name);
        const response = await fetchWithTimeout("/decode-qr", { method: "POST", body: form });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || t("errors.uploadQr"));
        document.getElementById("qrCodeInput").value = data.code;
        await submitQrCode();
    } catch (error) {
        showError("qrError", `${error.message}`);
    }
    navigate("result");
}

let scannerInterval = null;

async function startScanner() {
    const video = document.getElementById("scannerVideo");
    const overlay = document.getElementById("scannerOverlay");
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
        video.srcObject = stream;
        video.hidden = false;
        video.play();
        overlay.hidden = true;

        if (!("BarcodeDetector" in window)) {
            if (scannerInterval) clearInterval(scannerInterval);
            return;
        }

        const detector = new BarcodeDetector({ formats: ["qr_code"] });
        const canvas = document.getElementById("scannerCanvas");
        const ctx = canvas.getContext("2d");

        scannerInterval = setInterval(async () => {
            if (video.readyState !== video.HAVE_ENOUGH_DATA) return;
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            ctx.drawImage(video, 0, 0);
            try {
                const barcodes = await detector.detect(canvas);
                if (barcodes.length > 0) {
                    const code = barcodes[0].rawValue;
                    if (code.startsWith("https://") || code.startsWith("http://")) {
                        clearInterval(scannerInterval);
                        stream.getTracks().forEach((track) => track.stop());
                        video.hidden = true;
                        overlay.hidden = false;
                        document.getElementById("qrCodeInput").value = code;
                        await submitQrCode();
                    }
                }
            } catch (e) {
                console.debug("[Scanner] Frame detect error:", e);
            }
        }, 200);
    } catch (err) {
        video.hidden = true;
        overlay.hidden = false;
        showError("scannerError", "Camera access denied. Paste your QR code below.");
        console.error("[Scanner] Camera error:", err);
    }
}

async function generateDemoQr() {
    const productId = document.getElementById("demoProduct").value;
    try {
        const response = await fetchWithTimeout("/admin/issue-demo-codes", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ product_id: productId, count: 1 }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || t("errors.demoFail"));
        const code = data.codes[0];
        document.getElementById("qrCodeInput").value = code;
        const output = document.getElementById("generatedQr");
        output.innerHTML = `
            <p style="margin-bottom:var(--ag-space-sm); font-weight:600;">Generated unique code:</p>
            <img class="qr-image" alt="Generated product QR code" src="${data.qr_images[0]}">
            <a download="agroguard-demo-qr.png" href="${data.qr_images[0]}">Download QR image</a>
            <p class="code-text">${code}</p>
        `;
        output.classList.remove("hidden");
    } catch (error) {
        showError("issuerError", error.message);
    }
}

async function fetchWithTimeout(url, options) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90000);
    try {
        return await fetch(url, { ...options, signal: controller.signal });
    } catch (error) {
        if (error.name === "AbortError") throw new Error(t("errors.timeout"));
        throw error;
    } finally {
        clearTimeout(timer);
    }
}

function renderDiagnosis(data) {
    const badge = STATUS_BADGE[data.status] || STATUS_BADGE["uncertain"];
    setResultBadge(badge.cls, badge.icon);
    setCategory("result.category.diagnosis");
    setQuickInfo(`status.${data.status}`, badge.dot);

    const titleKey = t(`result.title.${data.status}`);
    const subtitleKey = t(`result.subtitle.${data.status}`);

    document.getElementById("resultTitle").textContent = titleKey || data.status;
    document.getElementById("resultSummary").textContent = subtitleKey || (data.retake_reason || data.explanation_localized || "The image was analyzed.");

    const cropText = t("fields.crop") || "Crop";
    const conditionText = t("fields.condition") || "Condition";
    const recText = t("fields.recommended") || "Recommended ingredients";
    const ctrlText = t("fields.culturalControls") || "Cultural controls";
    const evidenceText = t("fields.evidence") || "Visible evidence";
    const diffText = t("fields.differential") || "Differential";
    const diagIdText = t("fields.diagnosisId") || "Diagnosis ID";

    const differential = (data.differential || []).map((item) => {
        const ev = item.visible_evidence || [];
        const evHtml = ev.length ? `<div class="field-row" style="padding:0.2rem 0; display:block;"><span style="color:var(--ag-on-surface-variant); font-size:0.8rem;">${ev.map(e => "• " + e).join("<br>")}</span></div>` : "";
        return `
            <div class="field-row">
                <span class="field-label">${item.condition}</span>
                <span class="field-value" style="color:${item.agreement >= 0.5 ? 'var(--ag-trust)' : 'var(--ag-warning)'}">${Math.round(item.agreement * 100)}%</span>
            </div>
            ${evHtml}
        `;
    }).join("");

    let recommendedHtml = "";
    let controlsHtml = "";

    if (data.status === "ok") {
        const classes = data.recommended_ingredient_classes || [];
        if (classes.length) {
            recommendedHtml = `<div class="field-row"><span class="field-label">${recText}</span><span class="field-value">${classes.map(c => c.toUpperCase()).join(", ")}</span></div>`;
        }
    }

    const content = `
        <div class="field-row">
            <span class="field-label">${cropText}</span>
            <span class="field-value">${data.crop || "Not identified"}</span>
        </div>
        <div class="field-row">
            <span class="field-label">${conditionText}</span>
            <span class="field-value">${data.top_condition || "Not determined"}</span>
        </div>
        ${differential ? `<div class="field-row" style="margin-top:var(--ag-space-sm); border-top:1px solid var(--ag-outline-variant); padding-top:var(--ag-space-xs);">${diffText}</div>${differential}` : ""}
        ${recommendedHtml}
        ${controlsHtml}
    `;

    document.getElementById("resultContentInner").innerHTML = content;

    const explanationHtml = data.explanation_localized
        ? `<p style="font-size:0.9rem; line-height:1.5; color:var(--ag-on-surface-variant); margin-bottom:var(--ag-space-sm);">${data.explanation_localized}</p>`
        : "";
    const diagIdHtml = data.diagnosis_id
        ? `<div class="field-row"><span class="field-label">${diagIdText}</span><span class="field-value">${data.diagnosis_id}</span></div>`
        : "";

    document.getElementById("resultContentDetailsInner").innerHTML = explanationHtml + diagIdHtml;
    const detailsContent = document.getElementById("resultContentDetails");
    detailsContent.classList.add("hidden");
    document.querySelector(".btn-toggle").setAttribute("aria-expanded", "false");
    const toggleText = t("result.showDetails") || "Show details";
    document.querySelector(".btn-toggle").querySelector("span").textContent = toggleText;

    const actions = document.getElementById("resultActions");
    actions.innerHTML = `
        <button class="btn btn-secondary" onclick="navigate('verify')" data-i18n="result.checkProduct">Check the product I bought</button>
        <button class="btn btn-secondary" onclick="navigate('home')" data-i18n="result.backHome">Back to home</button>
`;
}

function renderQrResult(data) {
    const badge = VERDICT_BADGE[data.verdict] || VERDICT_BADGE["UNVERIFIABLE"];
    setResultBadge(badge.cls, badge.icon);
    setCategory("result.category.verification");
    setQuickInfo(`status.${data.verdict.toLowerCase()}`, badge.dot);
    const titleKey = t(`result.title.${data.verdict.toLowerCase()}`);
    document.getElementById("resultTitle").textContent = titleKey || data.verdict;
    document.getElementById("resultSummary").textContent = data.reason_human || "";

    const prod = data.product || {};
    const scanText = t("fields.scanCount") || "Scan count";
    const reasonText = t("fields.reason") || "Reason";
    const batchText = t("fields.batch") || "Batch";
    const expText = t("fields.expiry") || "Expiry";
    const mfrText = t("fields.manufacturer") || "Manufacturer";
    const prodText = t("fields.product") || "Product";
    const ingText = t("fields.ingredient") || "Ingredient class";

    const content = `
        <div class="field-row"><span class="field-label">${prodText}</span><span class="field-value">${prod.name || "Unknown"}</span></div>
        <div class="field-row"><span class="field-label">${mfrText}</span><span class="field-value">${prod.manufacturer || "Unknown"}</span></div>
        <div class="field-row"><span class="field-label">${batchText}</span><span class="field-value">${prod.batch || "Unknown"}</span></div>
        <div class="field-row"><span class="field-label">${expText}</span><span class="field-value">${prod.expiry || "Unknown"}</span></div>
        <div class="field-row"><span class="field-label">${ingText}</span><span class="field-value">${prod.active_ingredient_class || "Unknown"}</span></div>
        <div class="field-row" style="margin-top:var(--ag-space-sm);"><span class="field-label">${scanText}</span><span class="field-value">${data.scan_count}</span></div>
        <div class="field-row"><span class="field-label">${reasonText}</span><span class="field-value">${data.reason_code}</span></div>
    `;

    document.getElementById("resultContentInner").innerHTML = content;

    let detailsContent = "";
    if (data.matches_diagnosis !== undefined) {
        const matchText = data.matches_diagnosis ? "Matches diagnosis" : "Does not match diagnosis";
        detailsContent += `<div class="field-row"><span class="field-label">Diagnosis match</span><span class="field-value">${data.matches_diagnosis ? "✓" : "✕"}</span></div>`;
    }
    if (data.diagnosis_match_note) {
        detailsContent += `<p style="font-size:0.9rem; line-height:1.5; color:var(--ag-on-surface-variant); margin:var(--ag-space-sm) 0;">${data.diagnosis_match_note}</p>`;
    }
    detailsContent += `<div class="field-row"><span class="field-label">Verdict</span><span class="field-value">${data.verdict}</span></div>`;
    detailsContent += `<div class="field-row"><span class="field-label">${t("fields.reason") || "Reason"}</span><span class="field-value">${data.reason_code}</span></div>`;

    document.getElementById("resultContentDetailsInner").innerHTML = detailsContent;
    const detailsContentEl = document.getElementById("resultContentDetails");
    detailsContentEl.classList.add("hidden");
    document.querySelector(".btn-toggle").setAttribute("aria-expanded", "false");
    const toggleText = t("result.showDetails") || "Show details";
    document.querySelector(".btn-toggle").querySelector("span").textContent = toggleText;

    const actions = document.getElementById("resultActions");
    actions.innerHTML = `
        <button class="btn btn-secondary" onclick="navigate('verify')" data-i18n="result.checkAnotherProduct">Check another product</button>
        <button class="btn btn-secondary" onclick="navigate('home')" data-i18n="result.backHome">Back to home</button>
`;
}

function renderProductResult(data) {
    const badge = VERDICT_BADGE[data.verdict] || VERDICT_BADGE["UNVERIFIABLE"];
    setResultBadge(badge.cls, badge.icon);
    setCategory("result.category.label");
    setQuickInfo(`status.${data.verdict.toLowerCase()}`, badge.dot);
    const titleKey = t(`result.title.${data.verdict.toLowerCase()}`);
    document.getElementById("resultTitle").textContent = titleKey || data.verdict;
    document.getElementById("resultSummary").textContent = data.reason_human || "";

    const fields = data.extracted_fields || {};
    const prodText = t("fields.product") || "Product";
    const batchText = t("fields.batch") || "Batch";
    const mfrText = t("fields.manufacturer") || "Manufacturer";
    const expText = t("fields.expiry") || "Expiry";
    const regText = t("fields.regNumber") || "Registration";
    const ingText = t("fields.ingredient") || "Ingredient";
    const anomalyText = t("fields.anomalies") || "Anomalies";

    const content = `
        <div class="field-row"><span class="field-label">${prodText}</span><span class="field-value">${fields.product_name || "Not read"}</span></div>
        <div class="field-row"><span class="field-label">${mfrText}</span><span class="field-value">${fields.manufacturer || "Not read"}</span></div>
        <div class="field-row"><span class="field-label">${batchText}</span><span class="field-value">${fields.batch || "Not read"}</span></div>
        <div class="field-row"><span class="field-label">${expText}</span><span class="field-value">${fields.expiry || "Not read"}</span></div>
        <div class="field-row"><span class="field-label">${ingText}</span><span class="field-value">${fields.active_ingredient || "Not read"}</span></div>
    `;

    document.getElementById("resultContentInner").innerHTML = content;

    let detailsContent = "";
    const anomalies = data.anomalies || [];
    if (anomalies.length) {
        detailsContent += `<div class="field-row" style="align-items:flex-start; margin-bottom:var(--ag-space-sm);"><span class="field-label">${anomalyText}</span><span class="field-value" style="text-align:right; text-transform:lowercase; font-weight:400;">${anomalies.join("; ")}</span></div>`;
    }
    if (data.registry_match) {
        const match = data.registry_match;
        detailsContent += `<div class="field-row"><span class="field-label">Registry match</span><span class="field-value">${match.name || match.product_id || "Found"}</span></div>`;
    }
    detailsContent += `<p style="font-size:0.85rem; line-height:1.4; color:var(--ag-on-surface-variant); margin-top:var(--ag-space-sm);">${t("result.noteLabel") || "A label photo cannot prove authenticity. Use a signed QR code for the provenance check."}</p>`;

    document.getElementById("resultContentDetailsInner").innerHTML = detailsContent;
    const detailsContentEl = document.getElementById("resultContentDetails");
    detailsContentEl.classList.add("hidden");
    document.querySelector(".btn-toggle").setAttribute("aria-expanded", "false");
    const toggleText = t("result.showDetails") || "Show details";
    document.querySelector(".btn-toggle").querySelector("span").textContent = toggleText;

    const actions = document.getElementById("resultActions");
    actions.innerHTML = `
        <button class="btn btn-secondary" onclick="navigate('verify')" data-i18n="result.backToVerify">Back to product check</button>
        <button class="btn btn-secondary" onclick="navigate('home')" data-i18n="result.backHome">Back to home</button>
`;
}

function toggleDetails() {
    const details = document.getElementById("resultContentDetails");
    const button = document.querySelector(".btn-toggle");
    const isHidden = details.classList.toggle("hidden");
    button.setAttribute("aria-expanded", String(!isHidden));
    const label = button.querySelector("span");
    label.textContent = isHidden
        ? (t("result.showDetails") || "Show details")
        : (t("result.hideDetails") || "Hide details");
}

function speakResult() {
    const text = document.getElementById("resultSummary").textContent;
    if (text && "speechSynthesis" in window) {
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
    }
}

document.getElementById("langSelect").addEventListener("change", (event) => {
    state.lang = event.target.value;
    CURRENT_LANG.value = state.lang;
    applyTranslations();
});

function init() {
    applyTranslations();
    if (window.innerWidth < 768) {
        document.documentElement.style.fontSize = "14px";
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
} else {
    init();
}
