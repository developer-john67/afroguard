const state = { cropFile: null, labelFile: null, lang: "en" };

function clientId() {
    let value = localStorage.getItem("agroguard_client_id");
    if (!value) { value = crypto.randomUUID(); localStorage.setItem("agroguard_client_id", value); }
    return value;
}

function navigate(screen) {
    document.querySelectorAll(".screen").forEach((item) => item.classList.remove("active"));
    const target = document.getElementById(screen);
    if (target) target.classList.add("active");
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
        if (!response.ok) throw new Error(data.detail || "Diagnosis request failed.");
        renderDiagnosis(data);
    } catch (error) {
        showError("diagnoseError", `${error.message} The local classifier could not complete. Try a smaller, clearer image.`);
    } finally {
        loading.classList.add("hidden");
        button.disabled = false;
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
        if (!response.ok) throw new Error(data.detail || "Label verification failed.");
        renderProductResult(data);
    } catch (error) {
        showError("labelError", `${error.message} Check that Ollama is running and try again.`);
    } finally {
        loading.classList.add("hidden");
        button.disabled = false;
    }
}

async function submitQrCode() {
    const code = document.getElementById("qrCodeInput").value.trim();
    if (!code) { showError("qrError", "Paste a QR value first."); return; }
    try {
        const response = await fetchWithTimeout("/verify-code", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ code, client_id: clientId() }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "QR verification failed.");
        document.getElementById("resultIcon").className = `result-icon${data.verdict === "GENUINE" ? "" : " warning"}`;
        document.getElementById("resultTitle").textContent = data.verdict;
        document.getElementById("resultSummary").textContent = data.reason_human;
        document.getElementById("resultContent").innerHTML = `<p><strong>Product:</strong> ${data.product.name || "Unknown"}</p><p><strong>Batch:</strong> ${data.product.batch || "Unknown"}</p><p><strong>Scan count:</strong> ${data.scan_count}</p><p><strong>Reason:</strong> ${data.reason_code}</p>`;
        document.getElementById("resultDetails").classList.remove("hidden");
        navigate("result");
    } catch (error) { showError("qrError", error.message); }
}

async function decodeQrImage(input) {
    const file = input.files && input.files[0];
    if (!file) return;
    try {
        const form = new FormData();
        form.append("image", file, file.name);
        const response = await fetchWithTimeout("/decode-qr", { method: "POST", body: form });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "No QR code was found in that image.");
        document.getElementById("qrCodeInput").value = data.code;
        await submitQrCode();
    } catch (error) {
        showError("qrError", `${error.message} Use a clear, tightly cropped QR image.`);
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
        if (!response.ok) throw new Error(data.detail || "Demo issuance failed.");
        const code = data.codes[0];
        document.getElementById("qrCodeInput").value = code;
        const output = document.getElementById("generatedQr");
        output.innerHTML = `<p>Generated unique code:</p><img class="qr-image" alt="Generated product QR code" src="${data.qr_images[0]}"><a download="agroguard-demo-qr.png" href="${data.qr_images[0]}">Download QR image</a><p class="code-text">${code}</p>`;
        output.classList.remove("hidden");
    } catch (error) { showError("issuerError", error.message); }
}

async function fetchWithTimeout(url, options) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90000);
    try {
        return await fetch(url, { ...options, signal: controller.signal });
    } catch (error) {
        if (error.name === "AbortError") throw new Error("The local model took too long. Try a smaller, clearer image.");
        throw error;
    } finally {
        clearTimeout(timer);
    }
}

function renderDiagnosis(data) {
    const uncertain = data.status !== "ok";
    document.getElementById("resultIcon").className = `result-icon${uncertain ? " warning" : ""}`;
    document.getElementById("resultTitle").textContent = uncertain ? "We need a clearer answer" : "Crop check complete";
    document.getElementById("resultSummary").textContent = data.retake_reason || data.explanation_localized || "The image was analyzed.";
    const content = document.getElementById("resultContent");
    const conditions = (data.differential || []).map((item) => `<li>${item.condition} (${Math.round(item.agreement * 100)}%)</li>`).join("");
    content.innerHTML = `<p><strong>Status:</strong> ${data.status}</p><p><strong>Crop:</strong> ${data.crop || "Not identified"}</p>${conditions ? `<p><strong>Possible conditions:</strong></p><ul>${conditions}</ul>` : ""}<p>${data.explanation_localized || "No additional explanation was returned."}</p>`;
    document.getElementById("resultDetails").classList.remove("hidden");
    navigate("result");
}

function renderProductResult(data) {
    const suspicious = data.verdict === "SUSPICIOUS";
    document.getElementById("resultIcon").className = `result-icon${suspicious ? " warning" : ""}`;
    document.getElementById("resultTitle").textContent = data.verdict;
    document.getElementById("resultSummary").textContent = data.reason_human;
    const fields = data.extracted_fields || {};
    document.getElementById("resultContent").innerHTML = `<p><strong>Product:</strong> ${fields.product_name || "Not read"}</p><p><strong>Batch:</strong> ${fields.batch || "Not read"}</p><p><strong>Manufacturer:</strong> ${fields.manufacturer || "Not read"}</p><p><strong>Note:</strong> A label photo cannot prove authenticity. Use a signed QR code for the provenance check.</p>`;
    document.getElementById("resultDetails").classList.remove("hidden");
    navigate("result");
}

function toggleDetails() {
    const content = document.getElementById("resultContent");
    const button = document.querySelector(".btn-toggle");
    const hidden = content.classList.toggle("hidden");
    button.setAttribute("aria-expanded", String(!hidden));
}

function speakResult() {
    const text = document.getElementById("resultSummary").textContent;
    if (text && "speechSynthesis" in window) window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}

document.getElementById("langSelect").addEventListener("change", (event) => { state.lang = event.target.value; });
