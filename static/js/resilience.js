// ========== RESILIENCE.JS COMPLET CORRIGÉ ==========

document.addEventListener('DOMContentLoaded', function () {
    const map = L.map('resilience-map').setView([48.86, 2.35], 10);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

    let layerStore = {}; // Stocke les couches actives
    let mainLayers = [];
    let aleaLayers = [];

    const fileInput = document.getElementById('resilience-files');
    const fileNamesContainer = document.getElementById('file-names-container');
    const uploadBtn = document.getElementById('resilience-upload-btn');

    const layerSelect = document.getElementById('layer-selector');
    const colorPicker = document.getElementById('color-picker');
    const tableContainer = document.getElementById('table-container');
    const tableSelector = document.getElementById('table-selector');
    const layerControls = document.getElementById('layer-controls');

    // === Nouveau : Formulaire création de vue matérialisée ===
    const layerMain = document.getElementById('layer-main');
    const layerAlea = document.getElementById('layer-alea');
    const viewNameInput = document.getElementById('view-name');
    const previewBtn = document.getElementById('preview-view-btn');
    const createBtn = document.getElementById('create-view-btn');
    const viewSummary = document.getElementById('view-summary');

    // --- Test aléas ---
    const aleaMainLayer = document.getElementById('alea-main-layer');
    const aleaRunBtn = document.getElementById('alea-run-btn');
    const aleaProgress = document.getElementById('alea-progress');
    const aleaLog = document.getElementById('alea-log');
    const aleaDownloadLink = document.getElementById('alea-download-link');

    // ========== Upload de fichiers ========== //
    const SHP_EXTS = new Set(['.shp', '.shx', '.dbf', '.prj', '.cpg', '.sbn', '.sbx']);
    const SHP_REQUIRED = ['.shp', '.shx', '.dbf'];
    const ALLOWED_EXTS = new Set(['.gpkg', '.shp', '.shx', '.dbf', '.prj', '.cpg', '.sbn', '.sbx']);
    let uploadDatasets = [];

    function getExt(filename) {
        const idx = filename.lastIndexOf('.');
        return idx >= 0 ? filename.slice(idx).toLowerCase() : '';
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

    fileInput.addEventListener('change', () => {
        fileNamesContainer.innerHTML = "";
        const allFiles = Array.from(fileInput.files);
        const files = allFiles.filter((file) => ALLOWED_EXTS.has(getExt(file.name)));
        const ignoredCount = allFiles.length - files.length;
        uploadDatasets = buildDatasets(files);

        if (!uploadDatasets.length) {
            fileNamesContainer.innerHTML = "<em>Aucun fichier GPKG ou shapefile détecté.</em>";
            return;
        }

        uploadDatasets.forEach((ds) => {
            const div = document.createElement('div');
            const extsInfo = ds.type === 'shp'
                ? `Extensions: ${ds.exts.join(', ')}`
                : 'Format: GPKG';
            const missingInfo = ds.missing.length
                ? `<div style="color:#b00; font-size:0.9em;">Manque: ${ds.missing.join(', ')}</div>`
                : '';
            div.innerHTML = `
                <label>Nom pour <strong>${ds.label}</strong> :</label>
                <input type="text" data-key="${ds.key}" placeholder="ex: inondation" required>
                <div style="color:#666; font-size:0.9em;">${extsInfo}</div>
                ${missingInfo}
            `;
            fileNamesContainer.appendChild(div);
        });

        if (ignoredCount > 0) {
            const note = document.createElement('div');
            note.style.color = '#666';
            note.style.fontSize = '0.9em';
            note.textContent = `${ignoredCount} fichier(s) ignoré(s) (format non supporté).`;
            fileNamesContainer.appendChild(note);
        }
    });

    uploadBtn.addEventListener('click', () => {
        const files = Array.from(fileInput.files).filter((file) => ALLOWED_EXTS.has(getExt(file.name)));
        if (!files.length) return alert("Veuillez sélectionner des fichiers GPKG ou Shapefile.");

        const missingRequired = uploadDatasets
            .filter((ds) => ds.type === 'shp' && ds.missing.length)
            .map((ds) => `${ds.label} (${ds.missing.join(', ')})`);
        if (missingRequired.length) {
            alert("Shapefile incomplet : " + missingRequired.join(' | '));
            return;
        }

        const inputMap = new Map();
        fileNamesContainer.querySelectorAll('input[data-key]').forEach((input) => {
            inputMap.set(input.dataset.key, (input.value || '').trim());
        });

        const names = {};
        const missingNames = [];
        uploadDatasets.forEach((ds) => {
            const value = inputMap.get(ds.key) || '';
            if (!value) {
                missingNames.push(ds.label);
            } else {
                names[ds.key] = value;
            }
        });
        if (missingNames.length) {
            alert("Veuillez donner un nom pour : " + missingNames.join(', '));
            return;
        }

        const formData = new FormData();
        Array.from(files).forEach((file) => {
            formData.append('files', file);
        });
        formData.append('names', JSON.stringify(names));

        // lock UI during upload
        uploadBtn.disabled = true;
        const originalLabel = uploadBtn.dataset.label || uploadBtn.textContent;
        uploadBtn.dataset.label = originalLabel;
        uploadBtn.textContent = "Import en cours...";

        fetch('/upload_resilience', { method: 'POST', body: formData })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'ok') {
                    alert("Importation réussie !");
                    updateLayerList();
                } else {
                    alert("Erreur serveur : " + data.message);
                }
            })
            .catch(err => alert("Erreur réseau : " + err.message))
            .finally(() => {
                uploadBtn.disabled = false;
                uploadBtn.textContent = uploadBtn.dataset.label || "Importer dans la Base";
            });
    });

    // --- Bouton test aléas ---
    if (aleaRunBtn) {
        aleaRunBtn.addEventListener('click', () => {
            const main = aleaMainLayer && aleaMainLayer.value;
            if (!main) {
                alert("Sélectionnez une couche principale.");
                return;
            }
            aleaRunBtn.disabled = true;
            aleaProgress.textContent = "Traitement en cours...";
            aleaLog.innerHTML = "";
            aleaDownloadLink.style.display = 'none';

            fetch('/alea_batch_run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ main_layer: main })
            })
                .then(r => r.json())
                .then(data => {
                    if (data.status !== 'ok') {
                        throw new Error(data.message || 'Erreur serveur');
                    }
                    // Progression détaillée
                    const logHtml = data.logs.map(l =>
                        `<div>Couche ${l.step}/${l.total} : ${l.layer} — ${l.seconds}s</div>`
                    ).join('');
                    aleaLog.innerHTML = logHtml;
                    aleaProgress.textContent = `Terminé : ${data.logs.length} couches traitées.`;
                    if (data.download_csv) {
                        aleaDownloadLink.href = data.download_csv;
                        aleaDownloadLink.style.display = 'inline';
                        aleaDownloadLink.textContent = "Télécharger le CSV";
                    }
                })
                .catch(err => {
                    aleaProgress.textContent = "Erreur";
                    alert(err.message);
                })
                .finally(() => {
                    aleaRunBtn.disabled = false;
                });
        });
    }

    // ========== Mise à jour des couches disponibles ========== //
   function updateLayerList() {
        // Selecteurs
        const layerMain = document.getElementById('layer-main');
        const layerAlea = document.getElementById('layer-alea');
        const layerSelect = document.getElementById('layer-selector');
        const tableSelector = document.getElementById('table-selector');
        const layerControls = document.getElementById('layer-controls');
        const aleaSupportList = document.getElementById('alea-support-list');
        layerSelect.innerHTML = '';
        tableSelector.innerHTML = '';
        layerControls.innerHTML = '';
        if (layerMain) layerMain.innerHTML = '';
        if (layerAlea) layerAlea.innerHTML = '';
        aleaSupportList.innerHTML = '';
        layerStore = {};

        // Charger couches principales (gauche)
        fetch('/resilience_layers')
            .then(r => r.json())
            .then(mainLayers => {
                // Pour le select principal
                mainLayers.forEach(layer => {
                    // Pour visualisation sur carte
                    const opt = document.createElement('option');
                    opt.value = layer;
                    opt.textContent = layer;
                    layerSelect.appendChild(opt);

                    // Pour table attributaire
                    const opt2 = document.createElement('option');
                    opt2.value = layer;
                    opt2.textContent = layer;
                    tableSelector.appendChild(opt2);

                    // Pour création de vue matérialisée
                    if (layerMain) {
                        const opt3 = document.createElement('option');
                        opt3.value = layer;
                        opt3.textContent = layer;
                        layerMain.appendChild(opt3);
                    }

                    // Pour test aléas
                    if (aleaMainLayer) {
                        const opt4 = document.createElement('option');
                        opt4.value = layer;
                        opt4.textContent = layer;
                        aleaMainLayer.appendChild(opt4);
                    }

                    // Gestion affichage/suppression
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
                        </select>
                        <button class="delete-layer-btn" data-layer="${layer}" style="margin-left:10px;">🗑 Supprimer</button>
                    `;
                    layerControls.appendChild(wrapper);
                });
            });

        // Charger couches support (droite)
        fetch('/resilience_layers_support')
            .then(r => r.json())
            .then(aleaLayers => {
                // Affichage juste en mode info à droite
                if (aleaSupportList) {
                    if (aleaLayers.length === 0) {
                        aleaSupportList.innerHTML = '<em>Aucune couche de support détectée.</em>';
                    } else {
                        aleaSupportList.innerHTML = aleaLayers
                            .map(layer => `<span style="background:#eef; border-radius:8px; padding:3px 9px; margin:2px 0; display:inline-block;">${layer}</span>`)
                            .join(' ');
                    }
                }
                // Pour création de vue matérialisée (multi-select)
                if (layerAlea) {
                    aleaLayers.forEach(layer => {
                        const opt = document.createElement('option');
                        opt.value = layer;
                        opt.textContent = layer;
                        layerAlea.appendChild(opt);
                    });
                }
                // Pour la table attributaire (lecture seule)
                aleaLayers.forEach(layer => {
                    const opt2 = document.createElement('option');
                    opt2.value = layer;
                    opt2.textContent = layer + " (support)";
                    tableSelector.appendChild(opt2);
                });
            })
            .catch(err => {
                if (aleaSupportList) aleaSupportList.innerHTML = '<span style="color:red">Erreur lors du chargement des couches support.</span>';
            });
    }



    // === Gestion création de vue matérialisée ===

    // Déclaration d'une variable pour suivre l'état
    let previewData = null;

    previewBtn.addEventListener('click', function() {
        const mainTable = layerMain.value;
        const aleaTables = Array.from(layerAlea.selectedOptions).map(o => o.value);
        const viewName = viewNameInput.value.trim();

        if (!mainTable || aleaTables.length === 0 || !viewName) {
            alert("Veuillez choisir une table principale, au moins une couche alea et un nom de vue.");
            return;
        }

        // Si le contenu est déjà chargé, on toggle simplement l'affichage
        if (previewData && viewSummary.innerHTML.includes('preview-content')) {
            const previewContent = document.getElementById('preview-content');
            const isVisible = previewContent.style.display !== 'none';
            
            previewContent.style.display = isVisible ? 'none' : '';
            previewBtn.innerHTML = isVisible 
                ? 'Aperçu de la vue matérialisée ▲' 
                : 'Aperçu de la vue matérialisée ▼';
            return;
        }

        // Sinon, on fait la requête pour charger les données
        fetch('/create_resilience_view', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                main_table: mainTable,
                alea_tables: aleaTables,
                view_name: viewName,
                preview_only: true
            })
        })
        .then(r => r.json())
        .then(res => {
            if (res.status === 'preview') {
                previewData = res; // On stocke les données pour éviter de recharger
                
                viewSummary.innerHTML = `
                    <div id="preview-content" style="margin-top:8px;">
                        <strong>Dépendances :</strong> ${res.dependencies.join(', ')}<br>
                        <strong>Description&nbsp;:</strong><br>
                        <div style="margin:8px 0 12px 0; color:#235;">
                            ${res.description}
                        </div>
                        <strong>SQL généré :</strong>
                        <div class="sql-preview-block">${res.sql}</div>
                    </div>
                `;
                
                // On met à jour le texte du bouton avec la flèche
                previewBtn.innerHTML = 'Aperçu de la vue matérialisée ▼';
            } else {
                viewSummary.innerHTML = `<span style="color:red;">Erreur : ${res.message}</span>`;
            }
        })
        .catch(e => {
            viewSummary.innerHTML = `<span style="color:red;">Erreur réseau : ${e.message}</span>`;
        });
    });

    createBtn.addEventListener('click', () => {
        const mainTable = layerMain.value;
        const aleaTables = Array.from(layerAlea.selectedOptions).map(o => o.value);
        const viewName = viewNameInput.value.trim();

        if (!mainTable || aleaTables.length === 0 || !viewName) {
            alert("Veuillez choisir une table principale, au moins une couche alea et un nom de vue.");
            return;
        }

        fetch('/create_resilience_view', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                main_table: mainTable,
                alea_tables: aleaTables,
                view_name: viewName
            })
        })
        .then(r => r.json())
        .then(res => {
            if (res.status === 'ok') {
                alert("✅ Vue créée avec succès.");
                viewSummary.innerHTML = '';
                updateLayerList();
            } else {
                alert("❌ Erreur : " + res.message + "\n\n" + (res.sql || ""));
            }
        })
        .catch(e => alert("Erreur réseau : " + e.message));
    });

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

    layerControls.addEventListener('click', function (e) {
        if (!e.target.classList.contains('delete-layer-btn')) return;
        const layer = e.target.dataset.layer;
        fetch(`/resilience_dependencies/${layer}`)
            .then(r => r.json())
            .then(data => {
                const deps = data.dependencies;
                let msg = `Voulez-vous vraiment supprimer la couche "${layer}" ?`;
                if (deps.length) {
                    msg += `\n\n⚠️ Utilisée dans :\n - ${deps.join("\n - ")}`;
                }
                msg += "\n\nCette action est irréversible.";

                if (confirm(msg)) {
                    fetch('/delete_resilience_layer', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ layer })
                    })
                    .then(r => r.json())
                    .then(result => {
                        if (result.status === 'ok') {
                            alert(`✅ Couche "${layer}" supprimée.`);
                            updateLayerList();
                            if (layerStore[layer]) {
                                map.removeLayer(layerStore[layer]);
                                delete layerStore[layer];
                            }
                        } else {
                            alert(`❌ Erreur : ${result.message}`);
                        }
                    });
                }
            });
    });

    updateLayerList(); // démarrage
});
