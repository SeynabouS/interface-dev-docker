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

    // ========== Upload de fichiers ========== //
    fileInput.addEventListener('change', () => {
        fileNamesContainer.innerHTML = "";
        Array.from(fileInput.files).forEach((file, index) => {
            const div = document.createElement('div');
            div.innerHTML = `
                <label for="name-${index}">Nom pour <strong>${file.name}</strong> :</label>
                <input type="text" name="name-${index}" data-index="${index}" placeholder="ex: inondation" required>
            `;
            fileNamesContainer.appendChild(div);
        });
    });

    uploadBtn.addEventListener('click', () => {
        const files = fileInput.files;
        if (!files.length) return alert("Veuillez sélectionner des fichiers GPKG.");

        const formData = new FormData();
        Array.from(files).forEach((file, index) => {
            const nameInput = document.querySelector(`input[name="name-${index}"]`);
            if (!nameInput || !nameInput.value.trim()) {
                alert(`Veuillez donner un nom au fichier ${file.name}`);
                return;
            }
            formData.append('files', file);
            formData.append(`name-${index}`, nameInput.value.trim());
        });

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
            .catch(err => alert("Erreur réseau : " + err.message));
    });

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
