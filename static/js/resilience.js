// ========== RESILIENCE.JS COMPLET CORRIGÉ ==========

document.addEventListener('DOMContentLoaded', function () {
    const map = L.map('resilience-map').setView([48.86, 2.35], 10);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
    window.__resilienceMap = map;

    let layerStore = {}; // Stocke les couches actives
    let mainLayers = [];
    let aleaLayers = [];

    const fileInput = document.getElementById('resilience-files');
    const fileNamesContainer = document.getElementById('file-names-container');
    const uploadBtn = document.getElementById('resilience-upload-btn');
    const analysisFileInput = document.getElementById('analysis-layer-files');
    const analysisFileNamesContainer = document.getElementById('analysis-file-names-container');
    const analysisUploadBtn = document.getElementById('analysis-upload-btn');

    const layerSelect = document.getElementById('layer-selector');
    const colorPicker = document.getElementById('color-picker');
    const tableContainer = document.getElementById('table-container');
    const tableSelector = document.getElementById('table-selector');
    const layerControls = document.getElementById('layer-controls');
    const impactMatrixContainer = document.getElementById('impact-matrix-container');
    const impactMatrixSaveBtn = document.getElementById('impact-matrix-save-btn');

    // === Sélection des couches pour vue matérialisée ===
    const layerAlea = document.getElementById('layer-alea');
    const aleaAllCheckbox = document.getElementById('alea-all');

    // --- Test aléas ---
    const aleaMainLayer = document.getElementById('alea-main-layer');
    const aleaRunBtn = document.getElementById('alea-run-btn');
    const aleaProgress = document.getElementById('alea-progress');
    const aleaLog = document.getElementById('alea-log');
    const aleaDownloadCsv = document.getElementById('alea-download-link');
    const aleaDownloadGpkg = document.getElementById('alea-download-gpkg');
    const aleaDownloadShp = document.getElementById('alea-download-shp');
    const aleaViewName = document.getElementById('alea-view-name');
    const aleaSupportList = document.getElementById('alea-support-list');
    const aleaSupportCount = document.getElementById('alea-support-count');
    const aleaSelectedCount = document.getElementById('alea-selected-count');
    const aleaSelectionHelper = document.getElementById('alea-selection-helper');
    const aleaClearBtn = document.getElementById('alea-clear-btn');
    const historyList = document.getElementById('history-list');
    const historySearchInput = document.getElementById('history-search');
    const historyRefreshBtn = document.getElementById('history-refresh-btn');
    const historySelectAll = document.getElementById('history-select-all');
    const historyDeleteSelectedBtn = document.getElementById('history-delete-selected-btn');
    const historyResetBtn = document.getElementById('history-reset-btn');
    const historySelectionInfo = document.getElementById('history-selection-info');
    const selectedRunIds = new Set();
    let historySearchTimer = null;
    const importFeedback = document.getElementById('import-feedback');
    let importFeedbackTimer = null;
    const analysisImportFeedback = document.getElementById('analysis-import-feedback');
    let analysisImportFeedbackTimer = null;
    const layerActionFeedback = document.getElementById('layer-action-feedback');
    let layerActionFeedbackTimer = null;
    const impactMatrixFeedback = document.getElementById('impact-matrix-feedback');
    let impactMatrixFeedbackTimer = null;

    // ========== Upload de fichiers ========== //
    const SHP_EXTS = new Set(['.shp', '.shx', '.dbf', '.prj', '.cpg', '.sbn', '.sbx']);
    const SHP_REQUIRED = ['.shp', '.shx', '.dbf'];
    const ALLOWED_EXTS = new Set(['.gpkg', '.shp', '.shx', '.dbf', '.prj', '.cpg', '.sbn', '.sbx']);
    let uploadDatasets = [];
    let analysisUploadDatasets = [];

    function getExt(filename) {
        const idx = filename.lastIndexOf('.');
        return idx >= 0 ? filename.slice(idx).toLowerCase() : '';
    }

    function escapeHtml(value) {
        return String(value)
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#39;');
    }

    function prettifyLayerName(layer) {
        const stripped = String(layer).replace(/^alea_/, '');
        const withSpaces = stripped.replaceAll('_', ' ').replace(/\s+/g, ' ').trim();
        if (!withSpaces) return String(layer);
        return withSpaces.replace(/\b\w/g, (c) => c.toUpperCase());
    }

    function layerTypeLabel(type) {
        if (type === 'materialized_view') return 'vue materialisee';
        if (type === 'view') return 'vue';
        if (type === 'table') return 'table';
        return 'objet';
    }

    function normalizeLayerDependencies(dependencies) {
        if (!Array.isArray(dependencies)) return [];
        return dependencies
            .map((dep) => {
                if (!dep) return null;
                if (typeof dep === 'string') {
                    const name = dep.trim();
                    return name ? { name, type: 'object', label: 'objet' } : null;
                }

                const name = String(dep.name || '').trim();
                if (!name) return null;

                const type = String(dep.type || 'object').trim();
                const label = String(dep.label || layerTypeLabel(type)).trim();
                return { name, type, label };
            })
            .filter(Boolean);
    }

    function buildLayerDeleteConfirmMessage(layer, details) {
        const typeLabel = layerTypeLabel(details && details.layer_type);
        const dependencies = normalizeLayerDependencies(details && details.dependencies);
        const lines = [
            `Suppression de la couche "${layer}"`,
            '',
            `Type detecte : ${typeLabel}.`,
            "Cette action supprimera definitivement cette couche de la base Resilience."
        ];

        if (dependencies.length) {
            lines.push(
                '',
                `Impact detecte : ${dependencies.length} dependance(s) seront aussi supprimee(s) en cascade :`
            );
            dependencies.forEach((dep) => {
                lines.push(`- ${dep.name} (${dep.label})`);
            });
        } else {
            lines.push('', 'Aucune dependance applicative detectee.');
        }

        lines.push('', 'Cette action est irreversible.', 'Confirmer la suppression ?');
        return lines.join('\n');
    }

    function buildLayerDeleteFallbackMessage(layer, errorMessage) {
        return [
            `Suppression de la couche "${layer}"`,
            '',
            "L'impact n'a pas pu etre verifie avant suppression.",
            `Detail : ${errorMessage || 'information indisponible'}.`,
            '',
            'La suppression reste irreversible.',
            'Souhaitez-vous continuer ?'
        ].join('\n');
    }

    function buildLayerDeleteSuccessMessage(result, layer) {
        const dependencies = normalizeLayerDependencies(result && result.dependencies);
        const lines = [
            `Suppression terminee pour la couche "${layer}".`
        ];

        if (dependencies.length) {
            lines.push(
                `${dependencies.length} dependance(s) ont aussi ete supprimee(s) en cascade : ${dependencies.map((dep) => dep.name).join(', ')}.`
            );
        } else {
            lines.push('Aucune dependance supplementaire n\'a ete supprimee.');
        }

        return lines.join(' ');
    }

    function buildLayerDeleteErrorMessage(layer, errorMessage) {
        return `Suppression impossible pour la couche "${layer}" : ${errorMessage || 'erreur inconnue.'}`;
    }

    function updateAleaSelectedCount() {
        if (!layerAlea || !aleaSelectedCount) return;
        const total = layerAlea.options.length;
        const selected = Array.from(layerAlea.selectedOptions).length;
        if (aleaAllCheckbox && aleaAllCheckbox.checked) {
            aleaSelectedCount.textContent = `Toutes (${total})`;
            return;
        }
        aleaSelectedCount.textContent = `${selected}/${total}`;
    }

    function syncAleaSelectionMode() {
        const useAll = aleaAllCheckbox ? aleaAllCheckbox.checked : true;
        if (layerAlea) {
            layerAlea.disabled = useAll;
            layerAlea.classList.toggle('is-disabled', useAll);
        }
        if (aleaSelectionHelper) {
            aleaSelectionHelper.textContent = useAll
                ? "Mode automatique: toutes les couches aléa seront injectées."
                : "Mode manuel: sélectionnez les couches de support à injecter.";
        }
        updateAleaSelectedCount();
    }

    function renderAleaSupportList() {
        if (!aleaSupportList) return;

        if (aleaSupportCount) {
            const total = aleaLayers.length;
            aleaSupportCount.textContent = `${total} couche${total > 1 ? 's' : ''}`;
        }

        if (!aleaLayers.length) {
            aleaSupportList.innerHTML = '<em>Aucune couche de support détectée.</em>';
            return;
        }

        aleaSupportList.innerHTML = aleaLayers.map((layer) => {
            const safeLayer = escapeHtml(layer);
            const safeTitle = escapeHtml(prettifyLayerName(layer));
            return `
                <div class="alea-chip">
                    <span class="chip-title">${safeTitle}</span>
                    <a href="#" class="chip-link" data-layer="${safeLayer}">Injecter</a>
                </div>
            `;
        }).join('');
    }

    function formatRunDate(isoString) {
        if (!isoString) return '-';
        const d = new Date(isoString);
        if (Number.isNaN(d.getTime())) return '-';
        return d.toLocaleString('fr-FR', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    function runStatusBadge(status) {
        const s = String(status || '').toLowerCase();
        if (s === 'done' || s === 'succes' || s === 'success') {
            return '<span class="bg-emerald-900/40 text-emerald-400 border border-emerald-800/50 px-2 py-1 rounded text-xs font-medium">Succès</span>';
        }
        if (s === 'error' || s === 'echec' || s === 'failed') {
            return '<span class="bg-red-900/40 text-red-400 border border-red-800/50 px-2 py-1 rounded text-xs font-medium">Erreur</span>';
        }
        return `<span class="bg-slate-800 border border-slate-700 text-slate-300 px-2 py-1 rounded text-xs font-medium">${escapeHtml(status || 'Inconnu')}</span>`;
    }

    function updateHistorySelectionUi() {
        const rowCheckboxes = historyList
            ? Array.from(historyList.querySelectorAll('input.history-select-run[type="checkbox"]'))
            : [];
        const checkedCount = rowCheckboxes.filter((cb) => cb.checked).length;
        const hasRows = rowCheckboxes.length > 0;

        if (historySelectAll) {
            historySelectAll.disabled = !hasRows;
            historySelectAll.checked = hasRows && checkedCount === rowCheckboxes.length;
            historySelectAll.indeterminate = hasRows && checkedCount > 0 && checkedCount < rowCheckboxes.length;
        }

        if (historyDeleteSelectedBtn) {
            historyDeleteSelectedBtn.disabled = selectedRunIds.size === 0;
        }

        if (historySelectionInfo) {
            if (selectedRunIds.size === 0) {
                historySelectionInfo.textContent = 'Aucun run sélectionné.';
            } else {
                const suffix = selectedRunIds.size > 1 ? 's' : '';
                historySelectionInfo.textContent = `${selectedRunIds.size} run${suffix} sélectionné${suffix}.`;
            }
        }
    }

    function renderHistoryRows(runs) {
        if (!historyList) return;
        if (!Array.isArray(runs) || runs.length === 0) {
            selectedRunIds.clear();
            historyList.innerHTML = `
                <tr>
                    <td class="py-3 px-4 text-slate-500" colspan="6">Aucun run trouvé.</td>
                </tr>
            `;
            updateHistorySelectionUi();
            return;
        }

        const visibleIds = new Set(
            runs
                .map((run) => String(run.run_id ?? '').trim())
                .filter((id) => id.length > 0)
        );
        Array.from(selectedRunIds).forEach((id) => {
            if (!visibleIds.has(id)) {
                selectedRunIds.delete(id);
            }
        });

        historyList.innerHTML = runs.map((run) => {
            const runIdRaw = String(run.run_id ?? '').trim();
            const runId = escapeHtml(runIdRaw);
            const isSelected = runIdRaw.length > 0 && selectedRunIds.has(runIdRaw);
            const checkedAttr = isSelected ? 'checked' : '';
            const mainLayer = escapeHtml(run.main_layer || '-');
            const viewName = escapeHtml(run.view_name || '');
            const stressRaw = Array.isArray(run.stress_layers)
                ? run.stress_layers
                : (typeof run.stress_layers === 'string' ? run.stress_layers.split(',') : []);
            const stressLayers = stressRaw
                .map((item) => String(item || '').trim())
                .filter((item) => item.length > 0);
            const stressText = stressLayers.length ? stressLayers.join(', ') : '-';
            const stressBadges = stressLayers.length
                ? stressLayers.map((layer) =>
                    `<span class="inline-flex items-center px-2 py-1 rounded border border-brand-800/60 bg-brand-900/20 text-brand-300 text-[11px]">${escapeHtml(layer)}</span>`
                ).join(' ')
                : '<span class="text-slate-500">-</span>';
            const safeStressTitle = escapeHtml(stressText);
            const createdAt = formatRunDate(run.created_at);
            const duration = run.duration_seconds ? `${Number(run.duration_seconds).toFixed(2)}s` : '';
            const csvHref = run.view_name ? `/download_resilience_layer/${encodeURIComponent(run.view_name)}?format=csv` : '#';
            const gpkgHref = run.view_name ? `/download_resilience_layer/${encodeURIComponent(run.view_name)}?format=gpkg` : '#';
            const shpHref = run.view_name ? `/download_resilience_layer/${encodeURIComponent(run.view_name)}?format=shp` : '#';
            const actions = run.view_name ? `
                <div class="flex justify-end gap-2">
                    <a class="bg-slate-800 border border-slate-700 hover:bg-slate-700 text-slate-200 px-2 py-1 rounded text-xs" href="${csvHref}" target="_blank" rel="noopener">CSV</a>
                    <a class="bg-slate-800 border border-slate-700 hover:bg-slate-700 text-slate-200 px-2 py-1 rounded text-xs" href="${gpkgHref}" target="_blank" rel="noopener">GPKG</a>
                    <a class="bg-slate-800 border border-slate-700 hover:bg-slate-700 text-slate-200 px-2 py-1 rounded text-xs" href="${shpHref}" target="_blank" rel="noopener">SHP</a>
                    <button type="button" class="history-open-table bg-brand-600/20 text-brand-400 border border-brand-500/30 hover:bg-brand-600 hover:text-white px-2 py-1 rounded text-xs font-medium transition-colors" data-view="${viewName}">Table</button>
                </div>
            ` : '<span class="text-slate-600 text-xs">-</span>';

            return `
                <tr class="hover:bg-slate-800/40 transition-colors">
                    <td class="py-3 px-4 text-center align-top">
                        <input type="checkbox" class="history-select-run accent-cyan-500" data-run-id="${runId}" ${checkedAttr}>
                    </td>
                    <td class="py-3 px-4">
                        <div class="font-mono text-brand-400">RUN-${runId}</div>
                        <div class="text-[11px] text-slate-500">${createdAt}${duration ? ` • ${duration}` : ''}</div>
                    </td>
                    <td class="py-3 px-4 text-slate-300">${mainLayer}</td>
                    <td class="py-3 px-4 text-slate-300 max-w-[520px] whitespace-normal break-words align-top leading-relaxed" title="${safeStressTitle}">${stressBadges}</td>
                    <td class="py-3 px-4">${runStatusBadge(run.status)}</td>
                    <td class="py-3 px-4 text-right">${actions}</td>
                </tr>
            `;
        }).join('');
        updateHistorySelectionUi();
    }

    function loadResilienceHistory() {
        if (!historyList) return;
        const q = historySearchInput ? historySearchInput.value.trim() : '';
        historyList.innerHTML = `
            <tr>
                <td class="py-3 px-4 text-slate-500" colspan="6">Chargement de l'historique...</td>
            </tr>
        `;
        if (historySelectAll) {
            historySelectAll.checked = false;
            historySelectAll.indeterminate = false;
            historySelectAll.disabled = true;
        }
        fetch(`/resilience_runs_history?q=${encodeURIComponent(q)}`)
            .then((r) => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            })
            .then((runs) => renderHistoryRows(runs))
            .catch((e) => {
                historyList.innerHTML = `
                    <tr>
                        <td class="py-3 px-4 text-red-400" colspan="6">Erreur de chargement de l'historique: ${escapeHtml(e.message)}</td>
                    </tr>
                `;
                updateHistorySelectionUi();
            });
    }

    window.loadResilienceHistory = loadResilienceHistory;

    function showFeedback(element, timerName, message, type = 'success', delay = 6000) {
        if (!element) return;

        if (timerName === 'import' && importFeedbackTimer) clearTimeout(importFeedbackTimer);
        if (timerName === 'analysis' && analysisImportFeedbackTimer) clearTimeout(analysisImportFeedbackTimer);
        if (timerName === 'layer' && layerActionFeedbackTimer) clearTimeout(layerActionFeedbackTimer);
        if (timerName === 'impact' && impactMatrixFeedbackTimer) clearTimeout(impactMatrixFeedbackTimer);

        element.classList.remove('hidden-element', 'success', 'error');
        element.classList.add(type === 'error' ? 'error' : 'success');
        element.textContent = message;

        const timer = setTimeout(() => {
            element.classList.add('hidden-element');
        }, delay);

        if (timerName === 'import') importFeedbackTimer = timer;
        if (timerName === 'analysis') analysisImportFeedbackTimer = timer;
        if (timerName === 'layer') layerActionFeedbackTimer = timer;
        if (timerName === 'impact') impactMatrixFeedbackTimer = timer;
    }

    function showImportFeedback(message, type = 'success') {
        showFeedback(importFeedback, 'import', message, type, 6000);
    }

    function showAnalysisImportFeedback(message, type = 'success') {
        showFeedback(analysisImportFeedback, 'analysis', message, type, 6000);
    }

    function showLayerActionFeedback(message, type = 'success') {
        showFeedback(layerActionFeedback, 'layer', message, type, 8000);
    }

    function showImpactMatrixFeedback(message, type = 'success') {
        showFeedback(impactMatrixFeedback, 'impact', message, type, 7000);
    }

    function renderImpactMatrix(payload) {
        if (!impactMatrixContainer) return;

        const levels = Array.isArray(payload && payload.levels) ? payload.levels : [];
        const layers = Array.isArray(payload && payload.layers) ? payload.layers : [];

        if (!layers.length || !levels.length) {
            impactMatrixContainer.innerHTML = '<em>Aucune couche d\'aléa configurée pour la matrice.</em>';
            return;
        }

        const headerCells = levels.map((level) => `
            <th>Niveau ${escapeHtml(String(level))}</th>
        `).join('');

        const bodyRows = layers.map((layer) => {
            const layerName = String(layer.layer_name || '').trim();
            const safeLayer = escapeHtml(layerName);
            const title = escapeHtml(prettifyLayerName(layerName));
            const cells = levels.map((level) => {
                const rawValue = layer && layer.values ? layer.values[String(level)] : 0;
                const value = rawValue === null || rawValue === undefined ? 0 : rawValue;
                return `
                    <td>
                        <input
                            type="number"
                            step="any"
                            class="impact-matrix-input"
                            data-layer="${safeLayer}"
                            data-level="${escapeHtml(String(level))}"
                            value="${escapeHtml(String(value))}"
                        >
                    </td>
                `;
            }).join('');

            return `
                <tr>
                    <th class="impact-matrix-row-label">
                        <div class="impact-matrix-header">
                            <div class="impact-matrix-title">${title}</div>
                            <button type="button" class="impact-matrix-delete" data-layer="${safeLayer}">Supprimer</button>
                        </div>
                    </th>
                    ${cells}
                </tr>
            `;
        }).join('');

        impactMatrixContainer.innerHTML = `
            <table>
                <thead>
                    <tr>
                        <th>Couche d'aléa</th>
                        ${headerCells}
                    </tr>
                </thead>
                <tbody>
                    ${bodyRows}
                </tbody>
            </table>
        `;
    }

    function loadImpactMatrix() {
        if (!impactMatrixContainer) return;
        impactMatrixContainer.innerHTML = '<em>Chargement de la matrice des impacts...</em>';

        fetch('/resilience_impact_matrix')
            .then((r) => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            })
            .then((payload) => {
                if (payload.status === 'error') throw new Error(payload.message || 'Erreur matrice');
                renderImpactMatrix(payload);
            })
            .catch((err) => {
                impactMatrixContainer.innerHTML = `<em>Erreur de chargement: ${escapeHtml(err.message)}</em>`;
            });
    }

    async function saveImpactMatrix() {
        if (!impactMatrixContainer) return;

        const values = {};
        impactMatrixContainer.querySelectorAll('.impact-matrix-input[data-layer][data-level]').forEach((input) => {
            const layer = String(input.dataset.layer || '').trim();
            const level = String(input.dataset.level || '').trim();
            if (!layer || !level) return;
            if (!values[layer]) values[layer] = {};
            values[layer][level] = input.value;
        });

        if (!Object.keys(values).length) {
            showImpactMatrixFeedback("Aucune valeur à enregistrer dans la matrice.", 'error');
            return;
        }

        if (impactMatrixSaveBtn) impactMatrixSaveBtn.disabled = true;
        try {
            const response = await fetch('/resilience_impact_matrix', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ values })
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || payload.status !== 'ok') {
                throw new Error(payload.message || `HTTP ${response.status}`);
            }

            showImpactMatrixFeedback("Matrice des impacts enregistrée.", 'success');
            loadImpactMatrix();
        } catch (err) {
            showImpactMatrixFeedback(`Enregistrement impossible: ${err.message}`, 'error');
        } finally {
            if (impactMatrixSaveBtn) impactMatrixSaveBtn.disabled = false;
        }
    }

    async function deleteResilienceLayer(layer, triggerButton = null) {
        const layerName = String(layer || '').trim();
        if (!layerName) return;

        let dependencyDetails = null;
        try {
            const dependencyResponse = await fetch(`/resilience_dependencies/${encodeURIComponent(layerName)}`);
            const dependencyPayload = await dependencyResponse.json().catch(() => ({}));
            if (!dependencyResponse.ok || dependencyPayload.status === 'error') {
                throw new Error(dependencyPayload.message || `HTTP ${dependencyResponse.status}`);
            }
            dependencyDetails = dependencyPayload;
        } catch (err) {
            const fallbackMessage = buildLayerDeleteFallbackMessage(layerName, err.message);
            if (!confirm(fallbackMessage)) {
                return;
            }
        }

        if (dependencyDetails && !confirm(buildLayerDeleteConfirmMessage(layerName, dependencyDetails))) {
            return;
        }

        let originalLabel = null;
        if (triggerButton) {
            triggerButton.disabled = true;
            originalLabel = triggerButton.textContent;
            triggerButton.textContent = 'Suppression...';
        }

        try {
            const response = await fetch('/delete_resilience_layer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ layer: layerName })
            });
            const result = await response.json().catch(() => ({}));
            if (!response.ok || result.status !== 'ok') {
                throw new Error(result.message || `HTTP ${response.status}`);
            }

            showLayerActionFeedback(buildLayerDeleteSuccessMessage(result, layerName), 'success');
            updateLayerList();
            if (layerStore[layerName]) {
                map.removeLayer(layerStore[layerName]);
                delete layerStore[layerName];
            }
        } catch (err) {
            showLayerActionFeedback(buildLayerDeleteErrorMessage(layerName, err.message), 'error');
        } finally {
            if (triggerButton) {
                triggerButton.disabled = false;
                triggerButton.textContent = originalLabel;
            }
        }
    }

    function buildDatasets(files) {
        const shapefileGroups = new Map();
        const gpkgFiles = [];

        files.forEach((file) => {
            const ext = getExt(file.name);
            if (ext === '.gpkg') {
                gpkgFiles.push(file);
                return;
            }
            if (SHP_EXTS.has(ext)) {
                const stem = file.name.slice(0, -ext.length);
                if (!shapefileGroups.has(stem)) {
                    shapefileGroups.set(stem, { exts: new Set() });
                }
                shapefileGroups.get(stem).exts.add(ext);
            }
        });

        const datasets = [];
        shapefileGroups.forEach((group, stem) => {
            if (!group.exts.has('.shp')) return;
            const missing = SHP_REQUIRED.filter((ext) => !group.exts.has(ext));
            datasets.push({
                key: `${stem}.shp`,
                type: 'shp',
                label: `${stem}.shp`,
                exts: Array.from(group.exts).sort(),
                missing
            });
        });

        gpkgFiles.forEach((file) => {
            datasets.push({
                key: file.name,
                type: 'gpkg',
                label: file.name,
                exts: ['.gpkg'],
                missing: []
            });
        });

        return datasets;
    }

    function getAllowedUploadFiles(fileInputEl) {
        return Array.from(fileInputEl ? fileInputEl.files : []).filter((file) => ALLOWED_EXTS.has(getExt(file.name)));
    }

    function renderDatasetInputs(fileInputEl, containerEl) {
        if (!containerEl) return [];

        containerEl.innerHTML = "";
        const allFiles = Array.from(fileInputEl ? fileInputEl.files : []);
        const files = allFiles.filter((file) => ALLOWED_EXTS.has(getExt(file.name)));
        const ignoredCount = allFiles.length - files.length;
        const datasets = buildDatasets(files);

        if (!datasets.length) {
            containerEl.innerHTML = "<em>Aucun fichier GPKG ou shapefile détecté.</em>";
            return [];
        }

        datasets.forEach((ds) => {
            const div = document.createElement('div');
            const extsInfo = ds.type === 'shp'
                ? `Extensions: ${ds.exts.join(', ')}`
                : 'Format: GPKG';
            const missingInfo = ds.missing.length
                ? `<div style="color:#b00; font-size:0.9em;">Manque: ${ds.missing.join(', ')}</div>`
                : '';
            div.innerHTML = `
                <label>Nom pour <strong>${ds.label}</strong> :</label>
                <input type="text" data-key="${ds.key}" placeholder="optionnel (sinon nom du fichier)">
                <div style="color:#666; font-size:0.9em;">${extsInfo}</div>
                <div style="color:#666; font-size:0.85em;">Laisser vide pour utiliser le nom du fichier.</div>
                ${missingInfo}
            `;
            containerEl.appendChild(div);
        });

        if (ignoredCount > 0) {
            const note = document.createElement('div');
            note.style.color = '#666';
            note.style.fontSize = '0.9em';
            note.textContent = `${ignoredCount} fichier(s) ignoré(s) (format non supporté).`;
            containerEl.appendChild(note);
        }

        return datasets;
    }

    function collectDatasetNames(containerEl) {
        const names = {};
        if (!containerEl) return names;

        containerEl.querySelectorAll('input[data-key]').forEach((input) => {
            const value = (input.value || '').trim();
            if (value) {
                names[input.dataset.key] = value;
            }
        });

        return names;
    }

    if (fileInput) {
        fileInput.addEventListener('change', () => {
            uploadDatasets = renderDatasetInputs(fileInput, fileNamesContainer);
        });
    }

    if (analysisFileInput) {
        analysisFileInput.addEventListener('change', () => {
            analysisUploadDatasets = renderDatasetInputs(analysisFileInput, analysisFileNamesContainer);
        });
    }

    if (uploadBtn) {
        uploadBtn.addEventListener('click', () => {
            const files = getAllowedUploadFiles(fileInput);
            if (importFeedback) importFeedback.classList.add('hidden-element');
            if (!files.length) return alert("Veuillez sélectionner des fichiers GPKG ou Shapefile.");

            const missingRequired = uploadDatasets
                .filter((ds) => ds.type === 'shp' && ds.missing.length)
                .map((ds) => `${ds.label} (${ds.missing.join(', ')})`);
            if (missingRequired.length) {
                alert("Shapefile incomplet : " + missingRequired.join(' | '));
                return;
            }

            const formData = new FormData();
            files.forEach((file) => {
                formData.append('files', file);
            });
            formData.append('names', JSON.stringify(collectDatasetNames(fileNamesContainer)));

            uploadBtn.disabled = true;
            const originalLabel = uploadBtn.dataset.label || uploadBtn.textContent;
            uploadBtn.dataset.label = originalLabel;
            uploadBtn.textContent = "Import en cours...";

            fetch('/upload_resilience', { method: 'POST', body: formData })
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'ok') {
                        const importedCount = Array.isArray(data.imported_layers) && data.imported_layers.length
                            ? data.imported_layers.length
                            : uploadDatasets.length;
                        showImportFeedback(`Importation réussie: ${importedCount} couche(s) aléa ajoutée(s).`, 'success');
                        updateLayerList();
                        fileInput.value = '';
                        fileNamesContainer.innerHTML = '';
                        uploadDatasets = [];
                    } else {
                        showImportFeedback("Erreur serveur: " + data.message, 'error');
                        alert("Erreur serveur : " + data.message);
                    }
                })
                .catch(err => {
                    showImportFeedback("Erreur réseau: " + err.message, 'error');
                    alert("Erreur réseau : " + err.message);
                })
                .finally(() => {
                    uploadBtn.disabled = false;
                    uploadBtn.textContent = uploadBtn.dataset.label || "Importer dans la Base";
                });
        });
    }

    if (analysisUploadBtn) {
        analysisUploadBtn.addEventListener('click', () => {
            const files = getAllowedUploadFiles(analysisFileInput);
            if (analysisImportFeedback) analysisImportFeedback.classList.add('hidden-element');
            if (!files.length) return alert("Veuillez sélectionner votre couche d'analyse (GPKG ou Shapefile).");

            const missingRequired = analysisUploadDatasets
                .filter((ds) => ds.type === 'shp' && ds.missing.length)
                .map((ds) => `${ds.label} (${ds.missing.join(', ')})`);
            if (missingRequired.length) {
                alert("Shapefile incomplet : " + missingRequired.join(' | '));
                return;
            }
            if (analysisUploadDatasets.length !== 1) {
                alert("Importez une seule couche principale à la fois pour l'analyse réseau.");
                return;
            }

            const formData = new FormData();
            files.forEach((file) => {
                formData.append('files', file);
            });
            formData.append('names', JSON.stringify(collectDatasetNames(analysisFileNamesContainer)));

            analysisUploadBtn.disabled = true;
            const originalLabel = analysisUploadBtn.dataset.label || analysisUploadBtn.textContent;
            analysisUploadBtn.dataset.label = originalLabel;
            analysisUploadBtn.textContent = "Import en cours...";

            fetch('/upload_resilience_analysis_layer', { method: 'POST', body: formData })
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'ok') {
                        const importedLayers = Array.isArray(data.imported_layers) ? data.imported_layers : [];
                        const importedCount = importedLayers.length || analysisUploadDatasets.length;
                        showAnalysisImportFeedback(`Importation réussie: ${importedCount} couche temporaire prête pour l'analyse.`, 'success');
                        updateLayerList(importedLayers[0] || null);
                        analysisFileInput.value = '';
                        analysisFileNamesContainer.innerHTML = '';
                        analysisUploadDatasets = [];
                    } else {
                        showAnalysisImportFeedback("Erreur serveur: " + data.message, 'error');
                        alert("Erreur serveur : " + data.message);
                    }
                })
                .catch(err => {
                    showAnalysisImportFeedback("Erreur réseau: " + err.message, 'error');
                    alert("Erreur réseau : " + err.message);
                })
                .finally(() => {
                    analysisUploadBtn.disabled = false;
                    analysisUploadBtn.textContent = analysisUploadBtn.dataset.label || "Importer ma couche d'analyse";
                });
        });
    }

    if (layerAlea) {
        layerAlea.addEventListener('change', updateAleaSelectedCount);
    }

    if (aleaAllCheckbox) {
        aleaAllCheckbox.addEventListener('change', syncAleaSelectionMode);
    }

    if (aleaClearBtn) {
        aleaClearBtn.addEventListener('click', () => {
            if (!layerAlea) return;
            if (aleaAllCheckbox) aleaAllCheckbox.checked = false;
            Array.from(layerAlea.options).forEach((opt) => {
                opt.selected = false;
            });
            syncAleaSelectionMode();
            layerAlea.dispatchEvent(new Event('change'));
        });
    }

    if (aleaSupportList) {
        aleaSupportList.addEventListener('click', (event) => {
            const link = event.target.closest('.chip-link[data-layer]');
            if (!link || !layerAlea) return;
            event.preventDefault();

            const layer = link.dataset.layer;
            if (!layer) return;

            if (typeof window.switchTab === 'function') {
                window.switchTab('analyse');
            }

            if (aleaAllCheckbox) aleaAllCheckbox.checked = false;
            syncAleaSelectionMode();

            const targetOption = Array.from(layerAlea.options).find((opt) => opt.value === layer);
            if (targetOption) {
                targetOption.selected = true;
                layerAlea.dispatchEvent(new Event('change'));
            }

            layerAlea.focus();
        });
    }

    if (historySearchInput) {
        historySearchInput.addEventListener('input', () => {
            if (historySearchTimer) clearTimeout(historySearchTimer);
            historySearchTimer = setTimeout(() => {
                loadResilienceHistory();
            }, 220);
        });
    }

    if (historyRefreshBtn) {
        historyRefreshBtn.addEventListener('click', () => {
            loadResilienceHistory();
        });
    }

    if (historySelectAll) {
        historySelectAll.addEventListener('change', () => {
            if (!historyList) return;
            const runCheckboxes = Array.from(historyList.querySelectorAll('input.history-select-run[type="checkbox"]'));
            runCheckboxes.forEach((cb) => {
                cb.checked = historySelectAll.checked;
                const runId = String(cb.dataset.runId || '').trim();
                if (!runId) return;
                if (cb.checked) {
                    selectedRunIds.add(runId);
                } else {
                    selectedRunIds.delete(runId);
                }
            });
            updateHistorySelectionUi();
        });
    }

    if (historyDeleteSelectedBtn) {
        historyDeleteSelectedBtn.addEventListener('click', () => {
            const runIds = Array.from(selectedRunIds)
                .map((id) => Number.parseInt(id, 10))
                .filter((id) => Number.isInteger(id) && id > 0);
            if (!runIds.length) {
                alert('Sélectionnez au moins un run à supprimer.');
                return;
            }

            if (!confirm(`Supprimer ${runIds.length} run(s) sélectionné(s) ? Cette action est irréversible.`)) {
                return;
            }

            historyDeleteSelectedBtn.disabled = true;
            fetch('/resilience_runs_delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ run_ids: runIds })
            })
                .then(async (r) => {
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok || data.status !== 'ok') {
                        throw new Error(data.message || `HTTP ${r.status}`);
                    }
                    return data;
                })
                .then((data) => {
                    alert(`${data.deleted_count || 0} run(s) supprimé(s).`);
                    selectedRunIds.clear();
                    loadResilienceHistory();
                })
                .catch((e) => {
                    alert(`Erreur suppression: ${e.message}`);
                })
                .finally(() => {
                    historyDeleteSelectedBtn.disabled = selectedRunIds.size === 0;
                    updateHistorySelectionUi();
                });
        });
    }

    if (historyResetBtn) {
        historyResetBtn.addEventListener('click', () => {
            if (!confirm("Réinitialiser tout l'historique des runs ? Cette action est irréversible.")) {
                return;
            }

            historyResetBtn.disabled = true;
            fetch('/resilience_runs_reset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            })
                .then(async (r) => {
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok || data.status !== 'ok') {
                        throw new Error(data.message || `HTTP ${r.status}`);
                    }
                    return data;
                })
                .then(() => {
                    alert('Historique réinitialisé.');
                    selectedRunIds.clear();
                    loadResilienceHistory();
                })
                .catch((e) => {
                    alert(`Erreur réinitialisation: ${e.message}`);
                })
                .finally(() => {
                    historyResetBtn.disabled = false;
                    updateHistorySelectionUi();
                });
        });
    }

    if (historyList) {
        historyList.addEventListener('change', (event) => {
            const cb = event.target.closest('input.history-select-run[type="checkbox"]');
            if (!cb) return;
            const runId = String(cb.dataset.runId || '').trim();
            if (!runId) return;
            if (cb.checked) {
                selectedRunIds.add(runId);
            } else {
                selectedRunIds.delete(runId);
            }
            updateHistorySelectionUi();
        });

        historyList.addEventListener('click', (event) => {
            const btn = event.target.closest('.history-open-table[data-view]');
            if (!btn) return;
            const view = btn.dataset.view;
            if (!view) return;

            if (typeof window.switchTab === 'function') {
                window.switchTab('analyse');
            }
            updateLayerList();
            setTimeout(() => {
                const exists = Array.from(tableSelector.options).find((opt) => opt.value === view);
                if (!exists) {
                    const opt = document.createElement('option');
                    opt.value = view;
                    opt.textContent = view;
                    tableSelector.appendChild(opt);
                }
                tableSelector.value = view;
                loadAttributeTable(view);
            }, 350);
        });
    }

    // --- Création vue matérialisée aléas ---
    if (aleaRunBtn) {
        aleaRunBtn.addEventListener('click', () => {
            const main = aleaMainLayer && aleaMainLayer.value;
            if (!main) {
                alert("Sélectionnez une couche principale.");
                return;
            }
            const viewName = (aleaViewName && aleaViewName.value.trim()) || `${main}_alea_view`;
            const selectedAlea = Array.from(layerAlea ? layerAlea.selectedOptions : []).map(o => o.value);
            const useAll = aleaAllCheckbox ? aleaAllCheckbox.checked : true;

            if (!useAll && selectedAlea.length === 0) {
                alert("Sélectionnez au moins une couche aléa, ou activez l'option 'Prendre toutes les couches aléa'.");
                return;
            }

            aleaRunBtn.disabled = true;
            aleaProgress.textContent = "Création de la vue en cours...";
            aleaProgress.style.display = 'inline-block';
            aleaLog.innerHTML = "";
            if (aleaDownloadCsv) aleaDownloadCsv.style.display = 'none';
            if (aleaDownloadGpkg) aleaDownloadGpkg.style.display = 'none';
            if (aleaDownloadShp) aleaDownloadShp.style.display = 'none';

            const params = new URLSearchParams({ main_layer: main, view_name: viewName });
            if (!useAll && selectedAlea.length) {
                params.set('alea_tables', selectedAlea.join(','));
            }

            const es = new EventSource(`/alea_view_batch_stream?${params.toString()}`);
            es.onmessage = (evt) => {
                try {
                    const data = JSON.parse(evt.data);
                    if (data.status === 'progress') {
                        const line = `Couche ${data.step}/${data.total} : ${data.layer} — ${data.seconds}s`;
                        const div = document.createElement('div');
                        div.textContent = line;
                        aleaLog.appendChild(div);
                        aleaProgress.textContent = line;
                        aleaProgress.style.display = 'inline-block';
                    } else if (data.status === 'done') {
                        aleaProgress.textContent = `Vue "${data.view}" créée.`;
                        aleaProgress.style.display = 'inline-block';
                        if (aleaDownloadCsv && data.download_csv) {
                            aleaDownloadCsv.href = data.download_csv;
                            aleaDownloadCsv.textContent = "Télécharger CSV";
                            aleaDownloadCsv.style.display = 'inline';
                        }
                        if (aleaDownloadGpkg && data.download_gpkg) {
                            aleaDownloadGpkg.href = data.download_gpkg;
                            aleaDownloadGpkg.textContent = "Télécharger GPKG";
                            aleaDownloadGpkg.style.display = 'inline';
                        }
                        if (aleaDownloadShp && data.download_shp) {
                            aleaDownloadShp.href = data.download_shp;
                            aleaDownloadShp.textContent = "Télécharger Shapefile";
                            aleaDownloadShp.style.display = 'inline';
                        }
                        fetch('/resilience_analysis_layer_clear', { method: 'POST' })
                            .catch(() => null)
                            .finally(() => {
                                updateLayerList();
                            });
                        loadResilienceHistory();
                        es.close();
                        aleaRunBtn.disabled = false;
                    } else if (data.status === 'error') {
                        aleaProgress.textContent = "Erreur";
                        aleaProgress.style.display = 'inline-block';
                        alert(data.message || 'Erreur serveur');
                        loadResilienceHistory();
                        es.close();
                        aleaRunBtn.disabled = false;
                    }
                } catch (e) {
                    console.error(e);
                }
            };
            es.onerror = () => {
                aleaProgress.textContent = "Erreur";
                aleaProgress.style.display = 'inline-block';
                alert("Connexion interrompue.");
                es.close();
                aleaRunBtn.disabled = false;
            };
        });
    }

    // ========== Mise à jour des couches disponibles ========== //
    function updateLayerList(preferredAnalysisLayer = null) {
        const previousTableSelection = tableSelector ? tableSelector.value : '';
        const previousMapSelection = layerSelect ? layerSelect.value : '';
        const previousAnalysisSelection = preferredAnalysisLayer || (aleaMainLayer ? aleaMainLayer.value : '');
        const tableOptionValues = new Set();

        layerSelect.innerHTML = '';
        tableSelector.innerHTML = '';
        layerControls.innerHTML = '';
        if (layerAlea) layerAlea.innerHTML = '';
        if (aleaMainLayer) aleaMainLayer.innerHTML = '';
        if (aleaSupportList) aleaSupportList.innerHTML = '<em>Chargement des couches de support...</em>';
        if (aleaSupportCount) aleaSupportCount.textContent = '...';
        if (impactMatrixContainer) impactMatrixContainer.innerHTML = '<em>Chargement de la matrice des impacts...</em>';

        layerStore = {};
        mainLayers = [];
        aleaLayers = [];
        syncAleaSelectionMode();
        loadImpactMatrix();

        function appendTableOption(value, label = value) {
            if (!tableSelector || !value || tableOptionValues.has(value)) return;
            const opt = document.createElement('option');
            opt.value = value;
            opt.textContent = label;
            tableSelector.appendChild(opt);
            tableOptionValues.add(value);
        }

        function restoreSelections() {
            if (tableSelector && previousTableSelection) {
                const option = Array.from(tableSelector.options).find((opt) => opt.value === previousTableSelection);
                if (option) {
                    tableSelector.value = previousTableSelection;
                }
            }
            if (layerSelect && previousMapSelection) {
                const option = Array.from(layerSelect.options).find((opt) => opt.value === previousMapSelection);
                if (option) {
                    layerSelect.value = previousMapSelection;
                }
            }
        }

        // Charger les couches partagées pour la configuration cartographique.
        fetch('/resilience_layers')
            .then(r => r.json())
            .then(layers => {
                mainLayers = Array.isArray(layers) ? layers : [];

                mainLayers.forEach(layer => {
                    const opt = document.createElement('option');
                    opt.value = layer;
                    opt.textContent = layer;
                    layerSelect.appendChild(opt);

                    appendTableOption(layer, layer);

                    const wrapper = document.createElement('div');
                    wrapper.style.marginBottom = '10px';
                    wrapper.innerHTML = `
                        <input type="checkbox" id="toggle-${layer}" class="layer-toggle" data-layer="${layer}">
                        <label for="toggle-${layer}"><strong>${layer}</strong></label>
                        <input type="color" class="layer-color" data-layer="${layer}" value="#005aa3" style="margin-left:10px;">
                        <select class="download-format" data-layer="${layer}" style="margin-left:10px;">
                            <option value="">⬇ Format</option>
                            <option value="csv">CSV</option>
                            <option value="html">HTML</option>
                            <option value="gpkg">GPKG</option>
                            <option value="shp">Shapefile</option>
                        </select>
                        <button class="delete-layer-btn" data-layer="${layer}" style="margin-left:10px;">🗑 Supprimer</button>
                    `;
                    layerControls.appendChild(wrapper);
                });
                restoreSelections();
            });

        // Charger les couches support (aléas) pour l'injection de stress.
        fetch('/resilience_layers_support')
            .then(r => r.json())
            .then(supportLayers => {
                aleaLayers = Array.isArray(supportLayers) ? supportLayers : [];
                renderAleaSupportList();

                // Pour création de vue matérialisée (multi-select)
                if (layerAlea) {
                    aleaLayers.forEach(layer => {
                        const opt = document.createElement('option');
                        opt.value = layer;
                        opt.textContent = layer;
                        layerAlea.appendChild(opt);
                    });
                }

                syncAleaSelectionMode();
            })
            .catch(() => {
                aleaLayers = [];
                if (aleaSupportList) aleaSupportList.innerHTML = '<em>Erreur lors du chargement des couches support.</em>';
                if (aleaSupportCount) aleaSupportCount.textContent = 'Erreur';
                syncAleaSelectionMode();
            });

        // Charger les couches privées d'analyse pour l'utilisateur courant.
        fetch('/resilience_analysis_layers')
            .then(r => r.json())
            .then(privateLayers => {
                const analysisLayers = Array.isArray(privateLayers) ? privateLayers : [];

                if (aleaMainLayer) {
                    if (!analysisLayers.length) {
                        const placeholder = document.createElement('option');
                        placeholder.value = '';
                        placeholder.textContent = 'Importez votre couche réseau temporaire';
                        aleaMainLayer.appendChild(placeholder);
                    } else {
                        analysisLayers.forEach((layer) => {
                            const opt = document.createElement('option');
                            opt.value = layer;
                            opt.textContent = layer;
                            aleaMainLayer.appendChild(opt);
                        });
                        const targetValue = preferredAnalysisLayer || previousAnalysisSelection;
                        const targetOption = Array.from(aleaMainLayer.options).find((opt) => opt.value === targetValue);
                        if (targetOption) {
                            aleaMainLayer.value = targetValue;
                        }
                    }
                }
                restoreSelections();
            })
            .catch(() => {
                if (aleaMainLayer) {
                    const placeholder = document.createElement('option');
                    placeholder.value = '';
                    placeholder.textContent = 'Erreur chargement couche temporaire';
                    aleaMainLayer.appendChild(placeholder);
                }
            });
    }



    // ========== Le reste de tes fonctionnalités Leaflet, download, suppression, table attributaire... ==========

    function displayLayer(layerName, color = "#005aa3") {
        // Supprime la couche si elle est déjà affichée
        if (layerStore[layerName]) {
            map.removeLayer(layerStore[layerName]);
            delete layerStore[layerName];
        }
        // Recharge la couche depuis le backend
        fetch(`/resilience_layer_data/${layerName}`)
            .then(r => r.json())
            .then(data => {
                if (data.status !== 'ok') throw new Error(data.message);

                const geo = L.geoJSON(data.features, {
                    style: { color },
                    pointToLayer: function (feature, latlng) {
                        return L.circleMarker(latlng, {
                            radius: 6,
                            color: color,
                            fillColor: color,
                            fillOpacity: 0.6
                        });
                    },
                    onEachFeature: (feature, layer) => {
                        const props = feature.properties || {};
                        const content = Object.entries(props)
                            .map(([k, v]) => `<strong>${k}</strong>: ${v}`)
                            .join('<br>');
                        layer.bindPopup(content);
                    }
                }).addTo(map);

                layerStore[layerName] = geo;
                map.fitBounds(geo.getBounds());
            })
            .catch(e => alert("Erreur : " + e.message));
    }

    function loadAttributeTable(layerName) {
        fetch(`/resilience_layer_data/${layerName}`)
            .then(r => r.json())
            .then(data => {
                if (data.status !== 'ok') throw new Error(data.message);

                const columns = data.columns.filter(c => c !== 'geometry');
                const rows = data.table;

                let html = `<table><thead><tr>${columns.map(c => `<th>${c}</th>`).join('')}</tr></thead><tbody>`;
                rows.forEach(row => {
                    html += `<tr>${columns.map(c => `<td>${row[c] ?? ''}</td>`).join('')}</tr>`;
                });
                html += '</tbody></table>';
                tableContainer.innerHTML = html;
            })
            .catch(e => {
                tableContainer.innerHTML = `<p style="color: red;">Erreur table : ${e.message}</p>`;
            });
    }

    tableSelector.addEventListener('change', () => {
        const selected = tableSelector.value;
        if (selected) loadAttributeTable(selected);
    });

    layerSelect.addEventListener('change', () => {
        displayLayer(layerSelect.value, colorPicker.value);
    });

    colorPicker.addEventListener('input', () => {
        if (layerSelect.value) displayLayer(layerSelect.value, colorPicker.value);
    });

    layerControls.addEventListener('change', function (e) {
        const layerName = e.target.dataset.layer;
        if (e.target.classList.contains('layer-toggle')) {
            const colorInput = document.querySelector(`input.layer-color[data-layer="${layerName}"]`);
            if (e.target.checked) displayLayer(layerName, colorInput.value);
            else if (layerStore[layerName]) map.removeLayer(layerStore[layerName]);
        }
        if (e.target.classList.contains('layer-color')) {
            const color = e.target.value;
            const checkbox = document.querySelector(`input.layer-toggle[data-layer="${layerName}"]`);
            if (checkbox.checked) {
                displayLayer(layerName, color);
            }
        }
        if (e.target.classList.contains('download-format')) {
            const layer = e.target.dataset.layer;
            const format = e.target.value;
            if (format) {
                window.open(`/download_resilience_layer/${layer}?format=${format}`, '_blank');
                e.target.value = '';
            }
        }
    });

    layerControls.addEventListener('click', async function (e) {
        const deleteBtn = e.target.closest('.delete-layer-btn');
        if (!deleteBtn) return;
        await deleteResilienceLayer(deleteBtn.dataset.layer, deleteBtn);
    });

    if (impactMatrixContainer) {
        impactMatrixContainer.addEventListener('click', async function (e) {
            const deleteBtn = e.target.closest('.impact-matrix-delete[data-layer]');
            if (!deleteBtn) return;
            await deleteResilienceLayer(deleteBtn.dataset.layer, deleteBtn);
        });
    }

    if (impactMatrixSaveBtn) {
        impactMatrixSaveBtn.addEventListener('click', () => {
            saveImpactMatrix();
        });
    }

    updateHistorySelectionUi();
    updateLayerList(); // démarrage
});
