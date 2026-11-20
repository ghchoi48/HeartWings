(() => {
    const button = document.getElementById("latest-download");
    if (!button) return;

    const fallbackUrl = button.href;
    let resolved = false;
    let navigating = false;

    async function resolveDownload() {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 8000);
        try {
            const response = await fetch(
                "https://api.github.com/repos/ghchoi48/HeartWings/releases/latest",
                {
                    headers: { Accept: "application/vnd.github+json" },
                    signal: controller.signal,
                },
            );
            if (!response.ok) throw new Error(`GitHub API: ${response.status}`);

            const release = await response.json();
            const executables = release.assets.filter(
                (asset) => /\.exe$/i.test(asset.name) && asset.browser_download_url,
            );
            const installer =
                executables.find((asset) => /windows-x64-setup\.exe$/i.test(asset.name)) ||
                executables.find((asset) => /-setup\.exe$/i.test(asset.name)) ||
                executables[0];
            button.href = installer ? installer.browser_download_url : fallbackUrl;
        } catch {
            // Keep the release page available when the API is unavailable.
            button.href = fallbackUrl;
        } finally {
            clearTimeout(timeout);
            resolved = true;
        }
    }

    const downloadReady = resolveDownload();
    button.addEventListener("click", async (event) => {
        if (resolved || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        if (navigating) return;
        navigating = true;
        button.setAttribute("aria-busy", "true");
        button.textContent = "최신 버전 확인 중…";
        await downloadReady;
        button.removeAttribute("aria-busy");
        button.textContent = "최신 버전 다운로드";
        navigating = false;
        window.location.assign(button.href);
    });
})();
