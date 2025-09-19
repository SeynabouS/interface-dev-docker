// Function to update the displayed file list
function updateFileList(event, type) {
    const files = event.target.files;
    const fileListElement = document.getElementById(`file-list-${type}`);

    // Vérifier si des fichiers sont sélectionnés
    if (files.length > 0) {
        // Afficher le nom du premier fichier ou dossier
        const selectedDirectory = files[0].webkitRelativePath
            ? files[0].webkitRelativePath.split("/")[0]
            : 'Dossier sélectionné : ' + files[0].name;

        document.getElementById(`selected-file-${type}`).textContent = selectedDirectory;
    } else {
        document.getElementById(`selected-file-${type}`).textContent = "Aucun dossier sélectionné";
    }

    // Nettoyer la liste actuelle
    fileListElement.innerHTML = '';

    // Afficher les fichiers sélectionnés
    Array.from(files).forEach(file => {
        const li = document.createElement('li');
        li.textContent = file.webkitRelativePath || file.name; // Afficher le chemin relatif ou le nom
        fileListElement.appendChild(li);
    });
}

// Function to upload the files via AJAX
function uploadFiles(type) {
    console.log(`Tentative d'importation pour le type: ${type}`);

    const fileInput = document.getElementById(`file-input-${type}`);
    const uploadButton = document.getElementById(`upload-btn-${type}`);
    const loadingIndicator = document.getElementById(`loading-indicator-${type}`);

    if (!fileInput) {
        console.error(`Aucun élément trouvé pour file-input-${type}`);
        return;
    }

    const files = fileInput.files;
    if (files.length === 0) {
        alert("Veuillez sélectionner un dossier à importer.");
        return;
    }

    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
        formData.append('file', files[i]);
    }

    const exportDate = document.getElementById(`export-date-${type}`).value;
    if (!exportDate) {
        alert("Veuillez entrer une date d'exportation.");
        return;
    }
    formData.append('export_date', exportDate);

    uploadButton.disabled = true;
    loadingIndicator.style.display = 'inline';

    fetch('/upload', {
        method: 'POST',
        body: formData,
        credentials: 'same-origin' // utile si une auth/CSRf existe
    })
    .then(async (response) => {
        const ct = response.headers.get('content-type') || '';
        console.log('Réponse upload:', response.status, response.statusText, ct);

        // Détecte une redirection (souvent vers login)
        if (response.redirected) {
            const dest = response.url;
            const text = await response.text().catch(() => '');
            throw new Error(`Redirection vers ${dest}. Êtes-vous authentifié ?\n${text.slice(0,200)}…`);
        }

        // Essaie JSON sinon fallback texte
        let body;
        if (ct.includes('application/json')) {
            body = await response.json().catch(() => null);
        } else {
            body = await response.text().catch(() => '');
        }

        if (!response.ok) {
            const msg = (body && typeof body === 'object')
                ? (body.message || JSON.stringify(body))
                : `HTTP ${response.status} ${response.statusText} — ${String(body).slice(0,200)}…`;
            throw new Error(msg);
        }

        return body;
    })
    .then((data) => {
        console.log('Upload success:', data);
        alert((data && data.message) ? data.message : 'Upload réussi');
    })
    .catch((error) => {
        console.error("Erreur lors de l'upload des fichiers:", error);
        alert('Erreur lors de l\'upload: ' + error.message);
    })
    .finally(() => {
        uploadButton.disabled = false;
        loadingIndicator.style.display = 'none';
    });
}


document.addEventListener('DOMContentLoaded', function () {
    // Assurez-vous que les éléments existent avant d'ajouter les écouteurs d'événements
    const singleFileInput = document.getElementById('file-input-single');
    const comparisonFileInputOld = document.getElementById('file-input-old');
    const comparisonFileInputNew = document.getElementById('file-input-new');

    const uploadBtnSingle = document.getElementById('upload-btn-single');
    const uploadBtnComparison = document.getElementById('upload-btn-comparison');

    if (singleFileInput) {
        singleFileInput.addEventListener('change', (event) => updateFileList(event, 'single'));
    } else {
        console.error("Élément 'file-input-single' introuvable");
    }

    if (comparisonFileInputOld) {
        comparisonFileInputOld.addEventListener('change', (event) => updateFileList(event, 'old'));
    } else {
        console.error("Élément 'file-input-old' introuvable");
    }

    if (comparisonFileInputNew) {
        comparisonFileInputNew.addEventListener('change', (event) => updateFileList(event, 'new'));
    } else {
        console.error("Élément 'file-input-new' introuvable");
    }

    if (uploadBtnSingle) {
        uploadBtnSingle.addEventListener('click', () => uploadFiles('single'));
    } else {
        console.error("Bouton 'upload-btn-single' introuvable");
    }

    if (uploadBtnComparison) {
        uploadBtnComparison.addEventListener('click', () => uploadFiles('comparison'));
    } else {
        console.error("Bouton 'upload-btn-comparison' introuvable");
    }


    // Gestion des analyses pour un seul export
    document.getElementById('analyze-bpe').addEventListener('click', () => runAnalysisSingle('BPEGraceTHD'));
    document.getElementById('analyze-cable').addEventListener('click', () => runAnalysisSingle('CABLEGraceTHD'));
    document.getElementById('analyze-chambre').addEventListener('click', () => runAnalysisSingle('CHAMBREGraceTHD'));
    document.getElementById('analyze-fourreaux').addEventListener('click', () => runAnalysisSingle('FOURREAUXGraceTHD'));

    // Gestion des comparaisons entre deux exports
    document.getElementById('compare-bpe').addEventListener('click', () => runComparison('BPECompare'));
    document.getElementById('compare-cable').addEventListener('click', () => runComparison('CABLECompare'));
    document.getElementById('compare-chambre').addEventListener('click', () => runComparison('CHAMBRECompare'));
    document.getElementById('compare-fourreaux').addEventListener('click', () => runComparison('FOURREAUXCompare'));
});



document.addEventListener('DOMContentLoaded', function() {
    const exportDateField = document.getElementById('export-date-single');
    const hiddenExportDateField = document.getElementById('hidden-export-date');

    // Synchroniser la valeur du champ existant avec le champ caché
    exportDateField.addEventListener('change', function() {
        hiddenExportDateField.value = exportDateField.value;
    });

    // S'assurer que le champ caché est mis à jour avant la soumission du formulaire
    const arboForm = document.querySelector('form[action="/arborescence_livrable"]');
    arboForm.addEventListener('submit', function(event) {
        if (!exportDateField.value) {
            alert("Veuillez sélectionner une date d'export.");
            event.preventDefault();
        } else {
            hiddenExportDateField.value = exportDateField.value;
        }
    });
});

document.addEventListener('DOMContentLoaded', function() {
    const exportDateField = document.getElementById('export-date-single');
    const hiddenExportDateCSV = document.getElementById('hidden-export-date-csv');

    // Synchroniser la valeur du champ existant avec le champ caché
    exportDateField.addEventListener('change', function() {
        hiddenExportDateCSV.value = exportDateField.value;
    });

    // S'assurer que le champ caché est mis à jour avant la soumission du formulaire
    const presenceCSVForm = document.querySelector('form[action="/presence_champ_csv"]');
    presenceCSVForm.addEventListener('submit', function(event) {
        if (!exportDateField.value) {
            alert("Veuillez sélectionner une date d'export.");
            event.preventDefault();
        } else {
            hiddenExportDateCSV.value = exportDateField.value;
        }
    });
});

// Function to run analysis for BPE
function runAnalysisBPE(event) {
    console.log("Analyse des BPE en cours...");

    const exportDateField = document.getElementById('export-date-single');
    const hiddenExportDateCSV = document.getElementById('hidden-export-date'); // Ajouter si nécessaire

    if (!exportDateField.value) {
        alert("Veuillez sélectionner une date d'export.");
        event.preventDefault(); // Empêcher toute action supplémentaire
        return;
    } else {
        hiddenExportDateCSV.value = exportDateField.value; // Mettre à jour la valeur cachée
    }

    // Désactiver le bouton et indiquer le chargement
    const analyzeButton = document.getElementById('analyze-bpe');
    const resultsContainer = document.getElementById('results-single');
    analyzeButton.disabled = true;
    resultsContainer.innerHTML = "<p>Analyse en cours...</p>";

    // Envoyer la requête AJAX
    fetch('/analyze_bpe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ export_date: exportDateField.value })
    })
        .then(response => {
            if (!response.ok) {
                throw new Error("Erreur lors de l'analyse des BPE");
            }
            return response.json();
        })
        .then(data => {
            console.log("Analyse réussie :", data);

            // Construire le tableau des résultats
            let html = "<h3>Résultats de l'Analyse BPE</h3>";
            html += "<table border='1'><thead><tr><th>Type de BPE</th><th>Nombre sur le périmètre DSP (Territoire)</th><th>Nombre hors périmètre DSP</th><th>Nombre INDT</th></tr></thead><tbody>";
            data.results.forEach(row => {
                html += `<tr><td>${row['Type de BPE']}</td><td>${row['Nombre sur le perimetre de la DSP (Territoire)']}</td><td>${row['Nombre en dehors du perimetre de la DSP (Hors Territoire)']}</td><td>${row['Nombre en dehors du perimetre de la DSP (INDT)']}</td></tr>`;
            });
            html += "</tbody></table>";

            // Ajouter les liens pour télécharger les résultats
            html += `<div class="downloads">
                        <a href="${data.csv_path}" class="btn-download">Télécharger CSV</a>
                        <a href="${data.html_path}" class="btn-download">Télécharger HTML</a>
                    </div>`;

            resultsContainer.innerHTML = html;
        })
        .catch(error => {
            console.error("Erreur lors de l'analyse des BPE :", error);
            resultsContainer.innerHTML = `<p style="color: red;">Erreur : ${error.message}</p>`;
        })
        .finally(() => {
            analyzeButton.disabled = false; // Réactiver le bouton
        });
}

// Ajouter un écouteur d'événement pour appeler la fonction avec un `event`
document.addEventListener('DOMContentLoaded', function () {
    const analyzeBPEButton = document.getElementById('analyze-bpe');
    if (analyzeBPEButton) {
        analyzeBPEButton.addEventListener('click', function (event) {
            runAnalysisBPE(event); // Passer `event` pour pouvoir utiliser preventDefault()
        });
    } else {
        console.error("Bouton 'analyze-bpe' introuvable dans le DOM.");
    }
});



// Function to run analysis for CABLE
function runAnalysisCable(event) {
    console.log("Analyse des Câbles en cours...");

    const exportDateField = document.getElementById('export-date-single');
    const hiddenExportDateField = document.getElementById('hidden-export-date-cable'); // Champ caché pour la synchronisation

    // Validation de la date
    if (!exportDateField.value) {
        alert("Veuillez sélectionner une date d'export.");
        event.preventDefault(); // Empêcher toute autre action si la validation échoue
        return;
    } else {
        hiddenExportDateField.value = exportDateField.value; // Mettre à jour le champ caché
    }

    const analyzeButton = document.getElementById('analyze-cable');
    const resultsContainer = document.getElementById('results-single');
    analyzeButton.disabled = true;
    resultsContainer.innerHTML = "<p>Analyse en cours...</p>";

    fetch('/analyze_cable', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ export_date: exportDateField.value })
    })
        .then(response => {
            if (!response.ok) {
                throw new Error("Erreur lors de l'analyse des Câbles");
            }
            return response.json();
        })
        .then(data => {
            console.log("Analyse réussie :", data);

            // Construire le tableau des résultats
            let html = "<h3>Résultats de l'Analyse CABLE</h3>";
            html += "<table border='1'><thead><tr><th>cb_capafo</th><th>Nombre Total</th><th>Somme Longueur</th><th>Propriétaire</th><th>Territoire</th><th>Hors Territoire</th><th>INDT</th></tr></thead><tbody>";
            data.results.forEach(row => {
                html += `<tr>
                    <td>${row.cb_capafo}</td>
                    <td>${row.Nombre_Total}</td>
                    <td>${row.Somme_Longueur}</td>
                    <td>${row.Proprietaire}</td>
                    <td>${row.Territoire}</td>
                    <td>${row.Hors_Territoire}</td>
                    <td>${row.INDT}</td>
                </tr>`;
            });
            html += "</tbody></table>";

            // Ajouter les liens pour télécharger les résultats
            html += `<div class="downloads">
                        <a href="${data.csv_path}" class="btn-download">Télécharger CSV</a>
                        <a href="${data.html_path}" class="btn-download">Télécharger HTML</a>
                    </div>`;

            resultsContainer.innerHTML = html;
        })
        .catch(error => {
            console.error("Erreur lors de l'analyse des Câbles :", error);
            resultsContainer.innerHTML = `<p style="color: red;">Erreur : ${error.message}</p>`;
        })
        .finally(() => {
            analyzeButton.disabled = false; // Réactiver le bouton
        });
}

// Ajouter un écouteur d'événement pour le bouton Analyser CABLE
document.addEventListener('DOMContentLoaded', function () {
    const analyzeCableButton = document.getElementById('analyze-cable');
    if (analyzeCableButton) {
        analyzeCableButton.addEventListener('click', function (event) {
            runAnalysisCable(event); // Passer `event` pour utiliser preventDefault()
        });
    } else {
        console.error("Bouton 'analyze-cable' introuvable dans le DOM.");
    }
});


// Function to run analysis for CHAMBRE
function runAnalysisChambre(event) {
    console.log("Analyse des Chambres Techniques en cours...");

    const exportDateField = document.getElementById('export-date-single');
    const hiddenExportDateField = document.getElementById('hidden-export-date-chambre'); // Champ caché pour la synchronisation

    // Validation de la date
    if (!exportDateField.value) {
        alert("Veuillez sélectionner une date d'export.");
        event.preventDefault(); // Empêcher toute autre action si la validation échoue
        return;
    } else {
        hiddenExportDateField.value = exportDateField.value; // Mettre à jour le champ caché
    }

    const analyzeButton = document.getElementById('analyze-chambre');
    const resultsContainer = document.getElementById('results-single');
    analyzeButton.disabled = true;
    resultsContainer.innerHTML = "<p>Analyse en cours...</p>";

    fetch('/analyze_chambre', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ export_date: exportDateField.value })
    })
        .then(response => {
            if (!response.ok) {
                throw new Error("Erreur lors de l'analyse des Chambres Techniques");
            }
            return response.json();
        })
        .then(data => {
            console.log("Analyse réussie :", data);

            // Construire le tableau des résultats
            let html = "<h3>Résultats de l'Analyse des Chambres Techniques</h3>";
            html += "<table border='1'><thead><tr><th>Nature de chambre</th><th>Nombre DSP Irise</th><th>Nombre Location</th><th>Nombre Total</th><th>Territoire</th><th>Hors Territoire</th><th>INDT</th></tr></thead><tbody>";
            data.results.forEach(row => {
                html += `<tr>
                    <td>${row['Nature de chambre']}</td>
                    <td>${row['Nombre de chambres DSP Irise']}</td>
                    <td>${row['Nombre de chambres (location)']}</td>
                    <td>${row['Nombre total']}</td>
                    <td>${row['Territoire']}</td>
                    <td>${row['Hors Territoire']}</td>
                    <td>${row['INDT']}</td>
                </tr>`;
            });
            html += "</tbody></table>";

            // Ajouter les liens pour télécharger les résultats
            html += `<div class="downloads">
                        <a href="${data.csv_path}" class="btn-download">Télécharger CSV</a>
                        <a href="${data.html_path}" class="btn-download">Télécharger HTML</a>
                    </div>`;

            resultsContainer.innerHTML = html;
        })
        .catch(error => {
            console.error("Erreur lors de l'analyse des Chambres Techniques :", error);
            resultsContainer.innerHTML = `<p style="color: red;">Erreur : ${error.message}</p>`;
        })
        .finally(() => {
            analyzeButton.disabled = false; // Réactiver le bouton
        });
}

// Ajouter un écouteur d'événement pour le bouton Analyser CHAMBRE
document.addEventListener('DOMContentLoaded', function () {
    const analyzeChambreButton = document.getElementById('analyze-chambre');
    if (analyzeChambreButton) {
        analyzeChambreButton.addEventListener('click', function (event) {
            runAnalysisChambre(event); 
        });
    } else {
        console.error("Bouton 'analyze-chambre' introuvable dans le DOM.");
    }
});


// Fonction pour lancer l'analyse des fourreaux
function runAnalysisFourreaux() {
    console.log("Analyse des Fourreaux en cours...");

    const exportDateField = document.getElementById('export-date-single');
    const exportDate = exportDateField ? exportDateField.value : null;

    if (!exportDate) {
        alert("Veuillez sélectionner une date d'export.");
        return;
    }

    // Mettre à jour le champ caché export_date dans le formulaire
    document.getElementById('hidden-export-date-fourreaux').value = exportDate;

    const analyzeButton = document.getElementById('analyze-fourreaux');
    const resultsContainer = document.getElementById('results-single');
    analyzeButton.disabled = true;
    resultsContainer.innerHTML = "<p>Analyse en cours...</p>";

    // Créer le corps de la requête JSON
    const requestData = {
        export_date: exportDate
    };

    // Envoi de la requête avec fetch
    fetch('/analyze_fourreaux', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestData)
    })
    .then(response => {
        if (!response.ok) {
            console.log('Response was not OK: ', response);
            return response.text().then(text => {
                throw new Error('Server Error: ' + text);
            });
        }
        return response.json();  // Si la requête est réussie, on parse le JSON
    })
    .then(data => {
        console.log("Analyse réussie :", data);

        // Construire les tableaux des résultats pour conduites et cheminements
        let html = "<h3>Résultats de l'Analyse Fourreaux - Conduites</h3>";
        html += "<table border='1'><thead><tr><th>Propriétaire</th><th>Nombre de Fourreaux</th></tr></thead><tbody>";
        data.results_conduite.forEach(row => {
            html += `<tr><td>${row.Proprietaire}</td><td>${row['Nombre de fourreaux']}</td></tr>`;
        });
        html += "</tbody></table>";

        html += "<h3>Résultats de l'Analyse Fourreaux - Cheminements</h3>";
        html += "<table border='1'><thead><tr><th>Propriétaire</th><th>Nombre de Tronçons</th><th>Longueur GC (m)</th></tr></thead><tbody>";
        data.results_cheminement.forEach(row => {
            html += `<tr><td>${row.Proprietaire}</td><td>${row['Nombre de tronçons']}</td><td>${row['Longueur GC en m']}</td></tr>`;
        });
        html += "</tbody></table>";

        // Ajouter les liens pour télécharger les résultats
        html += `<div class="downloads">
                    <a href="${data.csv_path}" class="btn-download">Télécharger CSV</a>
                    <a href="${data.html_path}" class="btn-download">Télécharger HTML</a>
                </div>`;

        resultsContainer.innerHTML = html;
    })
    .catch(error => {
        console.error("Erreur lors de l'analyse des Fourreaux :", error);
        resultsContainer.innerHTML = `<p style="color: red;">Erreur : ${error.message}</p>`;
    })
    .finally(() => {
        analyzeButton.disabled = false;
    });
}

// Ajouter un écouteur d'événement pour le bouton Analyser Fourreaux
document.addEventListener('DOMContentLoaded', function () {
    const analyzeFourreauxButton = document.getElementById('analyze-fourreaux');
    if (analyzeFourreauxButton) {
        analyzeFourreauxButton.addEventListener('click', runAnalysisFourreaux);
    } else {
        console.error("Bouton 'analyze-fourreaux' introuvable dans le DOM.");
    }
});




function uploadFileExportDifferentVersion() {
    const oldFileInput = document.getElementById('file-input-old');
    const newFileInput = document.getElementById('file-input-new');
    const oldDate = document.getElementById('export-date-old').value;
    const newDate = document.getElementById('export-date-new').value;
    const loadingIndicator = document.getElementById('loading-indicator-different-version');
    const uploadButton = document.getElementById('upload-btn-different-version');

    // Vérification des éléments requis
    if (!oldFileInput || !newFileInput || !loadingIndicator || !uploadButton) {
        console.error("Éléments requis pour l'importation introuvables");
        return;
    }

    const oldFiles = oldFileInput.files;
    const newFiles = newFileInput.files;

    // Validation des fichiers sélectionnés
    if (oldFiles.length === 0 || newFiles.length === 0) {
        alert("Veuillez sélectionner des dossiers pour les deux exports.");
        return;
    }

    // Validation des dates
    if (!oldDate || !newDate) {
        alert("Veuillez entrer les dates d'exportation pour les deux dossiers.");
        return;
    }

    const formData = new FormData();

    // Ajouter les fichiers de l'ancien export
    Array.from(oldFiles).forEach(file => formData.append('old_files', file));
    formData.append('old_date', oldDate);

    // Ajouter les fichiers du nouvel export
    Array.from(newFiles).forEach(file => formData.append('new_files', file));
    formData.append('new_date', newDate);

    // Désactiver le bouton et afficher l'indicateur de chargement
    uploadButton.disabled = true;
    loadingIndicator.style.display = 'inline';

    // Envoi des fichiers via Fetch API
    fetch('/upload_different_version', {
        method: 'POST',
        body: formData
    })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => {
                    throw new Error(`Erreur serveur: ${err.message}`);
                });
            }
            return response.json();
        })
        .then(data => {
            console.log('Importation réussie :', data);
            alert('Importation réussie');
        })
        .catch(error => {
            console.error("Erreur lors de l'importation des fichiers :", error);
            alert("Erreur lors de l'importation : " + error.message);
        })
        .finally(() => {
            // Réactiver le bouton et cacher l'indicateur de chargement
            uploadButton.disabled = false;
            loadingIndicator.style.display = 'none';
        });
}


// Ajouter un gestionnaire d'événement pour le bouton
document.addEventListener('DOMContentLoaded', function () {
    const uploadDifferentVersionButton = document.getElementById('upload-btn-different-version');
    if (uploadDifferentVersionButton) {
        uploadDifferentVersionButton.addEventListener('click', uploadFileExportDifferentVersion);
    }
});


document.addEventListener('DOMContentLoaded', function () {
    const compareCableButton = document.getElementById('compare-cable-btn');
    const resultsComparisonContainer = document.getElementById('results-comparison');
    const oldDateInput = document.getElementById('export-date-old');
    const newDateInput = document.getElementById('export-date-new');

    if (!compareCableButton || !resultsComparisonContainer || !oldDateInput || !newDateInput) {
        console.error("Certains éléments nécessaires sont introuvables dans le DOM.");
        return;
    }

    compareCableButton.addEventListener('click', function () {
        const oldDate = oldDateInput.value;
        const newDate = newDateInput.value;

        if (!oldDate || !newDate) {
            alert("Veuillez sélectionner les deux dates d'export.");
            return;
        }

        resultsComparisonContainer.innerHTML = `
            <h3>Résultats de la Comparaison</h3>
            <p>Analyse en cours... Veuillez patienter.</p>
        `;

        fetch('/compare_cable', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_date: oldDate, new_date: newDate }),
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Erreur serveur : ${response.status} ${response.statusText}`);
                }
                return response.text();
            })
            .then(htmlContent => {
                resultsComparisonContainer.innerHTML = `
                    <h3>Résultats de la Comparaison</h3>
                    ${htmlContent}
                `;
            })
            .catch(error => {
                console.error("Erreur lors de la requête :", error);
                resultsComparisonContainer.innerHTML = `
                    <h3>Résultats de la Comparaison</h3>
                    <p class="error">Erreur lors de la comparaison : ${error.message}</p>
                `;
            });
    });
});



document.addEventListener('DOMContentLoaded', function () {
    const compareBPEButton = document.getElementById('compare-ebp-btn');
    const resultsComparisonContainer = document.getElementById('results-comparison');
    const oldDateInput = document.getElementById('export-date-old');
    const newDateInput = document.getElementById('export-date-new');

    if (!compareBPEButton || !resultsComparisonContainer || !oldDateInput || !newDateInput) {
        console.error("Certains éléments nécessaires sont introuvables dans le DOM.");
        return;
    }

    compareBPEButton.addEventListener('click', function () {
        const oldDate = oldDateInput.value;
        const newDate = newDateInput.value;

        if (!oldDate || !newDate) {
            alert("Veuillez sélectionner les deux dates d'export.");
            return;
        }

        resultsComparisonContainer.innerHTML = `
            <h3>Résultats de la Comparaison</h3>
            <p>Analyse en cours... Veuillez patienter.</p>
        `;

        fetch('/compare_ebp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_date: oldDate, new_date: newDate }),
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Erreur serveur : ${response.status} ${response.statusText}`);
                }
                return response.text();
            })
            .then(htmlContent => {
                resultsComparisonContainer.innerHTML = `
                    <h3>Résultats de la Comparaison</h3>
                    ${htmlContent}
                `;
            })
            .catch(error => {
                console.error("Erreur lors de la requête :", error);
                resultsComparisonContainer.innerHTML = `
                    <h3>Résultats de la Comparaison</h3>
                    <p class="error">Erreur lors de la comparaison : ${error.message}</p>
                `;
            });
    });
});



document.addEventListener('DOMContentLoaded', function () {
    const compareCheminementButton = document.getElementById('compare-cheminement-btn');
    const resultsComparisonContainer = document.getElementById('results-comparison');
    const oldDateInput = document.getElementById('export-date-old');
    const newDateInput = document.getElementById('export-date-new');

    if (!compareCheminementButton || !resultsComparisonContainer || !oldDateInput || !newDateInput) {
        console.error("Certains éléments nécessaires sont introuvables dans le DOM.");
        return;
    }

    compareCheminementButton.addEventListener('click', function () {
        const oldDate = oldDateInput.value;
        const newDate = newDateInput.value;

        if (!oldDate || !newDate) {
            alert("Veuillez sélectionner les deux dates d'export.");
            return;
        }

        resultsComparisonContainer.innerHTML = `
            <h3>Résultats de la Comparaison</h3>
            <p>Analyse en cours... Veuillez patienter.</p>
        `;

        fetch('/compare_cheminement', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_date: oldDate, new_date: newDate }),
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Erreur serveur : ${response.status} ${response.statusText}`);
                }
                return response.text();
            })
            .then(htmlContent => {
                resultsComparisonContainer.innerHTML = `
                    <h3>Résultats de la Comparaison</h3>
                    ${htmlContent}
                `;
            })
            .catch(error => {
                console.error("Erreur lors de la requête :", error);
                resultsComparisonContainer.innerHTML = `
                    <h3>Résultats de la Comparaison</h3>
                    <p class="error">Erreur lors de la comparaison : ${error.message}</p>
                `;
            });
    });
});


document.addEventListener('DOMContentLoaded', function () {
    // Sélectionner les éléments nécessaires
    const comparePointTechniqueButton = document.getElementById('compare-PointTechnique-btn');
    const resultsComparisonContainer = document.getElementById('results-comparison');
    const oldDateInput = document.getElementById('export-date-old');
    const newDateInput = document.getElementById('export-date-new');

    if (!comparePointTechniqueButton || !resultsComparisonContainer || !oldDateInput || !newDateInput) {
        console.error("Certains éléments nécessaires sont introuvables dans le DOM.");
        return;
    }

    // Ajouter un événement au bouton "Comparer PointTechnique"
    comparePointTechniqueButton.addEventListener('click', function () {
        const oldDate = oldDateInput.value;
        const newDate = newDateInput.value;

        // Vérifier que les dates sont fournies
        if (!oldDate || !newDate) {
            alert("Veuillez sélectionner les deux dates d'export.");
            return;
        }

        // Afficher un message d'attente dans le conteneur
        resultsComparisonContainer.innerHTML = `
            <h3>Résultats de la Comparaison</h3>
            <p>Analyse en cours... Veuillez patienter.</p>
        `;

        // Envoyer une requête POST au serveur Flask
        fetch('/compare_PointTechnique', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_date: oldDate, new_date: newDate })
        })
            .then(response => {
                if (!response.ok) {
                    console.error(`Erreur serveur : ${response.status} ${response.statusText}`);
                    throw new Error(`Erreur HTTP : ${response.status}`);
                }
                return response.text(); // Obtenir la réponse sous forme de texte HTML
            })
            .then(htmlContent => {
                // Insérer le contenu HTML retourné dans le conteneur
                resultsComparisonContainer.innerHTML = `
                    <h3>Résultats de la Comparaison</h3>
                    ${htmlContent}
                `;
            })
            .catch(error => {
                // Afficher une erreur en cas de problème
                console.error("Erreur lors de la requête :", error);
                resultsComparisonContainer.innerHTML = `
                    <h3>Résultats de la Comparaison</h3>
                    <p class="error">Erreur lors de la comparaison : ${error.message}</p>
                `;
            });
    });
});


document.addEventListener('DOMContentLoaded', function () {
    const compareSiteTechniqueButton = document.getElementById('compare-site-technique-btn');
    const resultsComparisonContainer = document.getElementById('results-comparison');
    const oldDateInput = document.getElementById('export-date-old');
    const newDateInput = document.getElementById('export-date-new');

    if (!compareSiteTechniqueButton || !resultsComparisonContainer || !oldDateInput || !newDateInput) {
        console.error("Certains éléments nécessaires sont introuvables dans le DOM.");
        return;
    }

    compareSiteTechniqueButton.addEventListener('click', function () {
        const oldDate = oldDateInput.value;
        const newDate = newDateInput.value;

        if (!oldDate || !newDate) {
            alert("Veuillez sélectionner les deux dates d'export.");
            return;
        }

        resultsComparisonContainer.innerHTML = `
            <h3>Résultats de la Comparaison</h3>
            <p>Analyse en cours... Veuillez patienter.</p>
        `;

        fetch('/compare_site_technique', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_date: oldDate, new_date: newDate }),
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Erreur serveur : ${response.status} ${response.statusText}`);
                }
                return response.text();
            })
            .then(htmlContent => {
                resultsComparisonContainer.innerHTML = `
                    <h3>Résultats de la Comparaison</h3>
                    ${htmlContent}
                `;
            })
            .catch(error => {
                console.error("Erreur lors de la requête :", error);
                resultsComparisonContainer.innerHTML = `
                    <h3>Résultats de la Comparaison</h3>
                    <p class="error">Erreur lors de la comparaison : ${error.message}</p>
                `;
            });
    });
});


//nouvelles fonctionnalités 
//table t_baie
// Fonction d'analyse pour t_baie
function runAnalysisTBaie() {
    console.log("Analyse de la table t_baie en cours...");

    const exportDateField = document.getElementById('export-date-single');
    const exportDate = exportDateField ? exportDateField.value : null;

    if (!exportDate) {
        alert("Veuillez sélectionner une date d'export.");
        return;
    }

    const analyzeButton = document.getElementById('analyze-t-baie');
    const resultsContainer = document.getElementById('results-section');
    const tableResults = document.getElementById('table-results');
    const downloadCsvLink = document.getElementById('download-results-csv');
    const downloadHtmlLink = document.getElementById('download-results-html');
    const analysisTitle = document.getElementById('analysis-title');

    analyzeButton.disabled = true;
    tableResults.innerHTML = "<p>Analyse en cours...</p>";

    // Cacher les boutons de téléchargement avant l'analyse
    downloadCsvLink.style.display = "none";
    downloadHtmlLink.style.display = "none";

    fetch('/analyze_t_baie', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ export_date: exportDate })
    })
    .then(response => response.json())
    .then(data => {
        console.log("Analyse réussie :", data);

        analysisTitle.innerText = `Résultats de l'Analyse t_baie (${exportDate})`;

        let html = `
            <p><strong>Unicité de ba_code :</strong> ${data.unique_percentage}% uniques, ${data.duplicate_percentage}% en double</p>
        `;

        if (data.duplicated_ba_codes.length > 0) {
            html += `<p><strong>Liste des ba_code dupliqués :</strong> ${data.duplicated_ba_codes.join(', ')}</p>`;
        }

        if (data.ba_rf_missing_values && data.ba_rf_missing_values.length > 0) {
            html += `<p><strong>ba_rf_code manquants :</strong> ${data.ba_rf_missing_values.join(', ')}</p>`;
        }

        html += `
            <table border="1">
                <thead>
                    <tr>
                        <th>Test</th>
                        <th>Nombre total de valeurs</th>
                        <th>Taux de réussite</th>
                        <th>Taux d'échec</th>
                        <th>Valeurs non trouvées</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Correspondance ba_lt_code (t_ltech.lt_code)</td>
                        <td>${data.ba_lt_total_checked}</td>
                        <td>${data.ba_lt_success_rate}%</td>
                        <td>${data.ba_lt_failure_rate}%</td>
                        <td>${data.ba_lt_missing_values.join(', ')}</td>
                    </tr>
                    <tr>
                        <td>Correspondance ba_rf_code (t_reference.rf_code)</td>
                        <td>${data.ba_rf_total_checked}</td>
                        <td>${data.ba_rf_success_rate}%</td>
                        <td>${data.ba_rf_failure_rate}%</td>
                        <td>${data.ba_rf_missing_values.join(', ')}</td>
                    </tr>
                </tbody>
            </table>
        `;

        tableResults.innerHTML = html;

        // Afficher les boutons de téléchargement si les fichiers existent
        if (data.csv_path) {
            downloadCsvLink.href = data.csv_path;
            downloadCsvLink.style.display = "inline-block";
        }
        if (data.html_path) {
            downloadHtmlLink.href = data.html_path;
            downloadHtmlLink.style.display = "inline-block";
        }

    })
    .catch(error => {
        console.error("Erreur lors de l'analyse de t_baie :", error);
        tableResults.innerHTML = `<p style="color: red;">Erreur : ${error.message}</p>`;
    })
    .finally(() => {
        analyzeButton.disabled = false;
    });
}

// Attachement de l'événement après le chargement du DOM
document.addEventListener('DOMContentLoaded', function () {
    const analyzeTBaieButton = document.getElementById('analyze-t-baie');
    if (analyzeTBaieButton) {
        analyzeTBaieButton.addEventListener('click', runAnalysisTBaie);
    }
});


// Fonction pour analyser la table t_cab_cond
function runAnalysisTCabCond() {
    console.log("Analyse de la table t_cab_cond en cours...");

    // Utilisez le bon sélecteur pour la date d'export
    const exportDateField = document.getElementById('export-date-single');
    const exportDate = exportDateField ? exportDateField.value : null;

    if (!exportDate) {
        alert("Veuillez sélectionner une date d'export.");
        return;
    }

    // Mettez à jour l'ID du bouton pour correspondre à votre HTML
    const analyzeButton = document.getElementById('analyze-t-cab-cond');
    
    // Utilisez les bons sélecteurs pour les éléments de résultats
    const resultsContainer = document.getElementById('results-section');
    const tableResults = document.getElementById('table-results');
    const downloadCsvLink = document.getElementById('download-results-csv');
    const downloadHtmlLink = document.getElementById('download-results-html');
    
    // Créez un conteneur d'erreur s'il n'existe pas
    let errorContainer = document.getElementById('error-container');
    if (!errorContainer) {
        errorContainer = document.createElement('div');
        errorContainer.id = 'error-container';
        resultsContainer.prepend(errorContainer);
    }

    // Réinitialisation de l'affichage
    analyzeButton.disabled = true;
    if (tableResults) tableResults.innerHTML = "<div class='loading'>Analyse en cours, veuillez patienter...</div>";
    errorContainer.innerHTML = "";
    if (downloadCsvLink) downloadCsvLink.style.display = "none";
    if (downloadHtmlLink) downloadHtmlLink.style.display = "none";

    fetch('/analyze_t_cab_cond', {
        method: 'POST',
        headers: { 
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        body: JSON.stringify({ export_date: exportDate })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(err => {
                throw new Error(err.message || "Erreur lors de la requête");
            });
        }
        return response.json();
    })
    .then(data => {
        if (data.status === "error") {
            throw new Error(data.message);
        }

        // Mise à jour du titre - vérifiez que l'élément existe
        const analysisTitle = document.getElementById('analysis-title');
        if (analysisTitle) {
            analysisTitle.textContent = `Résultats de l'Analyse t_cab_cond (${exportDate})`;
        }
        
        // Fonction helper pour formater les listes
        const formatList = (items, maxItems = 10) => {
            if (!items || !Array.isArray(items)) return "Aucun";
            if (items.length === 0) return "Aucun";
            if (items.length <= maxItems) return items.join(", ");
            return `${items.slice(0, maxItems).join(", ")}... (${items.length} au total)`;
        };
        

        // Construction du HTML seulement si tableResults existe
        if (tableResults) {
            let html = `
            <div class="analysis-section">
              <h3 class="section-title">Unicité des codes</h3>
              <table class="analysis-table">
                <thead>
                  <tr>
                    <th>Colonne</th>
                    <th>Taux d'unicité</th>
                    <th>Taux de duplication</th>
                    <th>Valeurs dupliquées</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>cc_cb_code</td>
                    <td>${data.cc_cb_unique_rate}%</td>
                    <td>${(100 - data.cc_cb_unique_rate).toFixed(2)}%</td>
                    <td>${formatList(data.duplicated_cc_cb)}</td>
                  </tr>
                  <tr>
                    <td>cc_cd_code</td>
                    <td>${data.cc_cd_unique_rate}%</td>
                    <td>${(100 - data.cc_cd_unique_rate).toFixed(2)}%</td>
                    <td>${formatList(data.duplicated_cc_cd)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            
            <div class="analysis-section">
              <h3 class="section-title">Correspondances</h3>
              <table class="analysis-table">
                <thead>
                  <tr>
                    <th>Relation</th>
                    <th>Total vérifié</th>
                    <th>Succès</th>
                    <th>Échec</th>
                    <th>Valeurs non trouvées</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>cc_cb_code → t_cable</td>
                    <td>${data.total_checked_cb}</td>
                    <td>${data.success_rate_cb}%</td>
                    <td>${data.failure_rate_cb}%</td>
                    <td>${formatList(data.valeurs_non_trouvees_cb)}</td>
                  </tr>
                  <tr>
                    <td>cc_cd_code → t_conduite</td>
                    <td>${data.total_checked_cd}</td>
                    <td>${data.success_rate_cd}%</td>
                    <td>${data.failure_rate_cd}%</td>
                    <td>${formatList(data.valeurs_non_trouvees_cd)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            
            <div class="analysis-section">
              <h3 class="section-title">Codes orphelins</h3>
              <table class="analysis-table">
                <thead>
                  <tr>
                    <th>Table</th>
                    <th>Codes orphelins</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>t_cable</td>
                    <td>${formatList(data.codes_orphelins_cable)}</td>
                  </tr>
                  <tr>
                    <td>t_conduite</td>
                    <td>${formatList(data.codes_orphelins_conduite)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            `;   

            tableResults.innerHTML = html;
        }

        // Gestion des liens de téléchargement seulement s'ils existent
        if (downloadCsvLink && data.csv_path) {
            downloadCsvLink.href = data.csv_path;
            downloadCsvLink.style.display = "inline-block";
            downloadCsvLink.textContent = "Télécharger CSV";
        }

        if (downloadHtmlLink && data.html_path) {
            downloadHtmlLink.href = data.html_path;
            downloadHtmlLink.style.display = "inline-block";
            downloadHtmlLink.textContent = "Télécharger HTML";
        }
    })
    .catch(error => {
        console.error("Erreur lors de l'analyse:", error);
        errorContainer.innerHTML = `
            <div class="error-message">
                <strong>Erreur lors de l'analyse:</strong>
                <p>${error.message}</p>
                <p>Veuillez vérifier que les fichiers nécessaires sont bien présents pour la date sélectionnée.</p>
            </div>
        `;
        if (tableResults) tableResults.innerHTML = "";
    })
    .finally(() => {
        if (analyzeButton) analyzeButton.disabled = false;
    });
}

// Initialisation - vérifiez que le bouton existe avant d'ajouter l'event listener
document.addEventListener('DOMContentLoaded', function() {
    const analyzeBtn = document.getElementById('analyze-t-cab-cond');
    if (analyzeBtn) {
        analyzeBtn.addEventListener('click', runAnalysisTCabCond);
    }
});

//bouton Analyser t_cassette.
function runAnalysisTCassette() {
    console.log("Analyse de la table t_cassette en cours...");

    const exportDate = document.getElementById('export-date-single')?.value;
    if (!exportDate) {
        alert("Veuillez sélectionner une date d'export.");
        return;
    }

    const analyzeButton = document.getElementById('analyze-t-cassette');
    const tableResults  = document.getElementById('table-results');
    const downloadCsv   = document.getElementById('download-results-csv');
    const downloadHtml  = document.getElementById('download-results-html');
    let   errorContainer= document.getElementById('error-container');
    if (!errorContainer) {
        errorContainer = document.createElement('div');
        errorContainer.id = 'error-container';
        document.getElementById('results-section').prepend(errorContainer);
    }

    analyzeButton.disabled = true;
    tableResults.innerHTML     = "<div class='loading'>Analyse en cours, veuillez patienter…</div>";
    errorContainer.innerHTML   = "";
    downloadCsv.style.display  = "none";
    downloadHtml.style.display = "none";

    // helper pour voir plus / moins
    function renderListWithToggle(list) {
        if (!list || list.length === 0) return "Aucune";
        const first10 = list.slice(0,10).join(", ");
        const rest   = list.slice(10);
        if (rest.length === 0) return first10;
        // génère HTML interactif
        return (
            first10 +
            ` <span class="toggle-more" onclick="
                this.style.display='none';
                this.nextElementSibling.style.display='inline';
            ">... Voir plus</span>` +
            `<span class="toggle-less" style="display:none" onclick="
                this.style.display='none';
                this.previousElementSibling.style.display='inline';
            ">, ${rest.join(", ")} <u>Voir moins</u></span>`
        );
    }

    fetch('/analyze_t_cassette', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ export_date: exportDate })
    })
    .then(r => r.ok ? r.json() : r.json().then(e => { throw new Error(e.message); }))
    .then(data => {
        if (data.status === "error") throw new Error(data.message);

        document.getElementById('analysis-title').textContent =
            `Résultats de l'Analyse t_cassette (${exportDate})`;

        const {
            total_cs_bp, total_cs_rf,
            cs_bp_unique_rate, cs_rf_unique_rate,
            duplicated_cs_bp, duplicated_cs_rf,
            success_rate_bp, success_rate_rf,
            non_trouve_bp, non_trouve_rf,
            cs_bp_vide, cs_rf_vide
        } = data;

        tableResults.innerHTML = `
<div class="analysis-section">
  <h3 class="section-title">Unicité des Codes</h3>
  <table class="analysis-table">
    <thead>
      <tr>
        <th>Colonne</th>
        <th>Total</th>
        <th>Taux (%)</th>
        <th>Doublons</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>cs_code</td>
        <td>${total_cs_bp}</td>
        <td>${cs_bp_unique_rate}%</td>
        <td>${renderListWithToggle(duplicated_cs_bp)}</td>
      </tr>
      <tr>
        <td>cs_rf_code</td>
        <td>${total_cs_rf}</td>
        <td>${cs_rf_unique_rate}%</td>
        <td>${renderListWithToggle(duplicated_cs_rf)}</td>
      </tr>
    </tbody>
  </table>
</div>

<div class="analysis-section">
  <h3 class="section-title">Correspondances</h3>
  <table class="analysis-table">
    <thead>
      <tr>
        <th>Relation</th>
        <th>Taux (%)</th>
        <th>Orphelins</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>cs_bp_code → t_ebp</td>
        <td>${success_rate_bp}%</td>
        <td>${renderListWithToggle(non_trouve_bp)}</td>
      </tr>
      <tr>
        <td>cs_rf_code → t_reference</td>
        <td>${success_rate_rf}%</td>
        <td>${renderListWithToggle(non_trouve_rf)}</td>
      </tr>
    </tbody>
  </table>
</div>

<div class="analysis-section">
  <h3 class="section-title">Codes Vides</h3>
  <table class="analysis-table">
    <thead>
      <tr>
        <th>Colonne</th>
        <th>Nombre de vides</th>
        <th>Exemples</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>cs_bp_code</td>
        <td>${cs_bp_vide}</td>
        <td>${renderListWithToggle([...Array(cs_bp_vide)].map((_,i)=>""))}</td>
      </tr>
      <tr>
        <td>cs_rf_code</td>
        <td>${cs_rf_vide}</td>
        <td>${renderListWithToggle([...Array(cs_rf_vide)].map((_,i)=>""))}</td>
      </tr>
    </tbody>
  </table>
</div>`;

        if (downloadCsv && data.csv_path) {
            downloadCsv.href    = data.csv_path;
            downloadCsv.style.display = "inline-block";
            downloadCsv.textContent   = "Télécharger CSV";
        }
        if (downloadHtml && data.html_path) {
            downloadHtml.href   = data.html_path;
            downloadHtml.style.display = "inline-block";
            downloadHtml.textContent   = "Télécharger HTML";
        }
    })
    .catch(err => {
        console.error(err);
        errorContainer.innerHTML = `
          <div class="error-message">
            <strong>Erreur :</strong> ${err.message}
          </div>`;
        tableResults.innerHTML = "";
    })
    .finally(() => analyzeButton.disabled = false);
}

document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('analyze-t-cassette');
    if (btn) btn.addEventListener('click', runAnalysisTCassette);
});



function runAnalysisTCondChem() {
    console.log("Analyse de la table t_cond_chem en cours...");

    const exportDateField = document.getElementById('export-date-single');
    const exportDate = exportDateField ? exportDateField.value : null;

    if (!exportDate) {
        alert("Veuillez sélectionner une date d'export.");
        return;
    }

    const analyzeButton = document.getElementById('analyze-t-cond-chem');
    const resultsContainer = document.getElementById('results-section');
    const tableResults = document.getElementById('table-results');
    const downloadCsvLink = document.getElementById('download-results-csv');
    const downloadHtmlLink = document.getElementById('download-results-html');

    let errorContainer = document.getElementById('error-container');
    if (!errorContainer) {
        errorContainer = document.createElement('div');
        errorContainer.id = 'error-container';
        resultsContainer.prepend(errorContainer);
    }

    analyzeButton.disabled = true;
    if (tableResults) tableResults.innerHTML = "<div class='loading'>Analyse en cours, veuillez patienter...</div>";
    errorContainer.innerHTML = "";
    if (downloadCsvLink) downloadCsvLink.style.display = "none";
    if (downloadHtmlLink) downloadHtmlLink.style.display = "none";

    fetch('/analyze_t_cond_chem', {
        method: 'POST',
        headers: { 
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        body: JSON.stringify({ export_date: exportDate })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(err => { throw new Error(err.message || "Erreur lors de la requête"); });
        }
        return response.json();
    })
    .then(data => {
        if (data.status === "error") {
            throw new Error(data.message);
        }

        const analysisTitle = document.getElementById('analysis-title');
        if (analysisTitle) {
            analysisTitle.textContent = `Résultats de l'Analyse t_cond_chem (${exportDate})`;
        }

        const formatList = (items) => {
            if (!items || items.length === 0) return "Aucun";
            return items.join(", ");
        };

        if (tableResults) {
            let html = `
            <div class="analysis-section">
                <h3 class="section-title">Unicité des Codes</h3>
                <table class="analysis-table">
                    <thead>
                        <tr>
                            <th>Colonne</th>
                            <th>Nombre total</th>
                            <th>Taux d'unicité</th>
                            <th>Doublons</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>dm_cd_code</td>
                            <td>${data.total_dm_cd}</td>
                            <td>${data.dm_cd_unique_rate}%</td>
                            <td>${formatList(data.duplicated_dm_cd)}</td>
                        </tr>
                        <tr>
                            <td>dm_cm_code</td>
                            <td>${data.total_dm_cm}</td>
                            <td>${data.dm_cm_unique_rate}%</td>
                            <td>${formatList(data.duplicated_dm_cm)}</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <div class="analysis-section">
                <h3 class="section-title">Correspondances</h3>
                <table class="analysis-table">
                    <thead>
                        <tr>
                            <th>Relation</th>
                            <th>Succès (%)</th>
                            <th>Échecs (codes non trouvés)</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>dm_cd_code → t_conduite</td>
                            <td>${data.success_rate_cd}%</td>
                            <td>${formatList(data.non_trouve_cd)}</td>
                        </tr>
                        <tr>
                            <td>dm_cm_code → t_cheminement</td>
                            <td>${data.success_rate_cm}%</td>
                            <td>${formatList(data.non_trouve_cm)}</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <div class="analysis-section">
                <h3 class="section-title">Codes Vides</h3>
                <table class="analysis-table">
                    <thead>
                        <tr>
                            <th>Colonne</th>
                            <th>Nombre de vides</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>dm_cd_code</td>
                            <td>${data.dm_cd_vide}</td>
                        </tr>
                        <tr>
                            <td>dm_cm_code</td>
                            <td>${data.dm_cm_vide}</td>
                        </tr>
                    </tbody>
                </table>
            </div>`;
            
            tableResults.innerHTML = html;
        }

        if (downloadCsvLink && data.csv_path) {
            downloadCsvLink.href = data.csv_path;
            downloadCsvLink.style.display = "inline-block";
            downloadCsvLink.textContent = "Télécharger CSV";
        }

        if (downloadHtmlLink && data.html_path) {
            downloadHtmlLink.href = data.html_path;
            downloadHtmlLink.style.display = "inline-block";
            downloadHtmlLink.textContent = "Télécharger HTML";
        }

    })
    .catch(error => {
        console.error("Erreur lors de l'analyse:", error);
        errorContainer.innerHTML = `
            <div class="error-message">
                <strong>Erreur lors de l'analyse :</strong>
                <p>${error.message}</p>
                <p>Veuillez vérifier que les tables nécessaires sont bien présentes pour la date sélectionnée.</p>
            </div>
        `;
        if (tableResults) tableResults.innerHTML = "";
    })
    .finally(() => {
        if (analyzeButton) analyzeButton.disabled = false;
    });
}

// Écoute du bouton
document.addEventListener('DOMContentLoaded', function() {
    const analyzeCondChemBtn = document.getElementById('analyze-t-cond-chem');
    if (analyzeCondChemBtn) {
        analyzeCondChemBtn.addEventListener('click', runAnalysisTCondChem);
    }
});

function runAnalysisCoherenceCable() {
    console.log("Analyse de la cohérence câble en cours...");

    const exportDateField = document.getElementById('export-date-single');
    const exportDate = exportDateField ? exportDateField.value : null;

    if (!exportDate) {
        alert("Veuillez sélectionner une date d'export.");
        return;
    }

    const analyzeButton = document.getElementById('analyze-coherence-cable');
    const resultsContainer = document.getElementById('results-section');
    const tableResults = document.getElementById('table-results');
    const downloadCsvLink = document.getElementById('download-results-csv');
    const downloadHtmlLink = document.getElementById('download-results-html');

    let errorContainer = document.getElementById('error-container');
    if (!errorContainer) {
        errorContainer = document.createElement('div');
        errorContainer.id = 'error-container';
        resultsContainer.prepend(errorContainer);
    }

    analyzeButton.disabled = true;
    if (tableResults) tableResults.innerHTML = "<div class='loading'>Analyse en cours, veuillez patienter...</div>";
    errorContainer.innerHTML = "";
    if (downloadCsvLink) downloadCsvLink.style.display = "none";
    if (downloadHtmlLink) downloadHtmlLink.style.display = "none";

    fetch('/analyze_coherence_cable', {
        method: 'POST',
        headers: { 
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        body: JSON.stringify({ export_date: exportDate })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(err => { throw new Error(err.message || "Erreur lors de la requête"); });
        }
        return response.json();
    })
    .then(data => {
        if (data.status === "error") throw new Error(data.message);

        const analysisTitle = document.getElementById('analysis-title');
        if (analysisTitle) {
            analysisTitle.textContent = `Résultats de l'Analyse cohérence câble (${exportDate})`;
        }

        const formatList = (items) => {
            if (!items || items.length === 0) return "Aucun";
            return items.join(", ");
        };

        if (tableResults) {
            let html = `
            <div class="analysis-section">
                <h3 class="section-title">cb_prop / cb_gest / cb_user non trouvés</h3>
                <table class="analysis-table">
                    <thead>
                        <tr><th>Champ</th><th>Valeurs non trouvées</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>cb_prop</td><td>${formatList(data.cb_prop_non_trouve)}</td></tr>
                        <tr><td>cb_gest</td><td>${formatList(data.cb_gest_non_trouve)}</td></tr>
                        <tr><td>cb_user</td><td>${formatList(data.cb_user_non_trouve)}</td></tr>
                    </tbody>
                </table>
            </div>

            <div class="analysis-section">
                <h3 class="section-title">Vérification cb_fo_disp + cb_fo_util = cb_capafo</h3>
                <p>Nombre de lignes incohérentes : <strong>${data.nb_incoherents_fo}</strong></p>
                ${data.incoherents_fo_html ? `
                    <table class="analysis-table">
                        <thead>
                            <tr>
                                <th>cb_code</th>
                                <th>cb_fo_disp</th>
                                <th>cb_fo_util</th>
                                <th>cb_capafo</th>
                                <th>Somme</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.incoherents_fo_html}
                        </tbody>
                    </table>
                ` : ''}
                
            </div>

            <div class="analysis-section">
                <h3 class="section-title">Vérification cb_codeext</h3>
                <p>Nombre de valeurs incorrectes : <strong>${data.nb_cb_codeext_invalides}</strong></p>
            </div>
            
          <div class="analysis-section">
            <h3 class="section-title">Unicité de cb_code</h3>
            <table class="analysis-table">
              <thead>
                <tr><th>Total</th><th>Taux (%)</th><th>Doublons</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>${data.total_cb_code}</td>
                  <td>${data.cb_code_unique_rate}%</td>
                  <td>${formatList(data.duplicated_cb_code)}</td>
                </tr>
              </tbody>
            </table>
          </div>`;
            tableResults.innerHTML = html;
        }

        if (downloadCsvLink && data.csv_path) {
            downloadCsvLink.href = data.csv_path;
            downloadCsvLink.style.display = "inline-block";
            downloadCsvLink.textContent = "Télécharger CSV";
        }

        if (downloadHtmlLink && data.html_path) {
            downloadHtmlLink.href = data.html_path;
            downloadHtmlLink.style.display = "inline-block";
            downloadHtmlLink.textContent = "Télécharger HTML";
        }

    })
    .catch(error => {
        console.error("Erreur lors de l'analyse:", error);
        errorContainer.innerHTML = `
            <div class="error-message">
                <strong>Erreur lors de l'analyse :</strong>
                <p>${error.message}</p>
                <p>Veuillez vérifier que les fichiers câble et organisme existent pour la date choisie.</p>
            </div>
        `;
        if (tableResults) tableResults.innerHTML = "";
    })
    .finally(() => {
        if (analyzeButton) analyzeButton.disabled = false;
    });
}

// Activation du bouton
document.addEventListener('DOMContentLoaded', function() {
    const analyzeCableBtn = document.getElementById('analyze-coherence-cable');
    if (analyzeCableBtn) {
        analyzeCableBtn.addEventListener('click', runAnalysisCoherenceCable);
    }
});

//table coherence t_conduite
function runAnalysisConduiteOrganisme() {
    const exportDateField = document.getElementById('export-date-single');
    const exportDate = exportDateField ? exportDateField.value : null;

    if (!exportDate) {
        alert("Veuillez sélectionner une date d'export.");
        return;
    }

    const button = document.getElementById('analyze-conduite-organisme');
    const tableResults = document.getElementById('table-results');
    const downloadCsvLink = document.getElementById('download-results-csv');
    const downloadHtmlLink = document.getElementById('download-results-html');
    const errorContainer = document.getElementById('error-container');

    button.disabled = true;
    tableResults.innerHTML = "<div class='loading'>Analyse en cours...</div>";
    if (downloadCsvLink) downloadCsvLink.style.display = "none";
    if (downloadHtmlLink) downloadHtmlLink.style.display = "none";
    if (errorContainer) errorContainer.innerHTML = "";

    fetch('/analyze_conduite_organisme', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ export_date: exportDate })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === "error") throw new Error(data.message);

        document.getElementById('analysis-title').textContent = `Analyse t_conduite → t_organisme (${exportDate})`;

        const formatList = (items) => items.length ? items.join(", ") : "Aucune";

        tableResults.innerHTML = `
        <div class="analysis-section">
          <h3 class="section-title">Unicité des codes</h3>
          <table class="analysis-table">
            <thead>
              <tr><th>Champ</th><th>Total</th><th>Taux unique (%)</th><th>Doublons</th></tr>
            </thead>
            <tbody>
              <tr><td>cd_code</td><td>${data.total_cd_code}</td><td>${data.cd_code_unique_rate}%</td><td>${formatList(data.duplicated_cd_code)}</td></tr>
              <tr><td>or_code</td><td>${data.total_or_code}</td><td>${data.or_code_unique_rate}%</td><td>${formatList(data.duplicated_or_code)}</td></tr>
            </tbody>
          </table>
        </div>
        <div class="analysis-section">
            <table class="analysis-table">
                <thead><tr><th>Champ</th><th>Valeurs non trouvées</th></tr></thead>
                <tbody>
                    <tr><td>cd_prop</td><td>${formatList(data.cd_prop_non_trouve)}</td></tr>
                    <tr><td>cd_gest</td><td>${formatList(data.cd_gest_non_trouve)}</td></tr>
                    <tr><td>cd_user</td><td>${formatList(data.cd_user_non_trouve)}</td></tr>
                </tbody>
            </table>
        </div>`;

        if (downloadCsvLink && data.csv_path) {
            downloadCsvLink.href = data.csv_path;
            downloadCsvLink.style.display = "inline-block";
        }

        if (downloadHtmlLink && data.html_path) {
            downloadHtmlLink.href = data.html_path;
            downloadHtmlLink.style.display = "inline-block";
        }
    })
    .catch(err => {
        console.error("Erreur:", err);
        if (errorContainer) {
            errorContainer.innerHTML = `<p class="error-message">Erreur : ${err.message}</p>`;
        }
    })
    .finally(() => {
        button.disabled = false;
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('analyze-conduite-organisme');
    if (btn) btn.addEventListener('click', runAnalysisConduiteOrganisme);
});


//cohérence table ebp/baie
function runAnalysisEBP() {
    console.log("Analyse de la table t_ebp en cours...");

    const exportDateField = document.getElementById('export-date-single');
    const exportDate = exportDateField ? exportDateField.value : null;

    if (!exportDate) {
        alert("Veuillez sélectionner une date d'export.");
        return;
    }

    const analyzeButton = document.getElementById('analyze-ebp');
    const resultsContainer = document.getElementById('results-section');
    const tableResults = document.getElementById('table-results');
    const downloadCsvLink = document.getElementById('download-results-csv');
    const downloadHtmlLink = document.getElementById('download-results-html');

    let errorContainer = document.getElementById('error-container');
    if (!errorContainer) {
        errorContainer = document.createElement('div');
        errorContainer.id = 'error-container';
        resultsContainer.prepend(errorContainer);
    }

    analyzeButton.disabled = true;
    tableResults.innerHTML = "<div class='loading'>Analyse en cours...</div>";
    errorContainer.innerHTML = "";
    if (downloadCsvLink) downloadCsvLink.style.display = "none";
    if (downloadHtmlLink) downloadHtmlLink.style.display = "none";

    fetch('/analyze_ebp', {
        method: 'POST',
        headers: { 
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        body: JSON.stringify({ export_date: exportDate })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(err => { throw new Error(err.message || "Erreur lors de la requête"); });
        }
        return response.json();
    })
    .then(data => {
        if (data.status === "error") {
            throw new Error(data.message);
        }

        document.getElementById('analysis-title').textContent = `Analyse t_ebp (${exportDate})`;

        const formatList = (items) => {
            if (!items || items.length === 0) return "Aucune";
            const visible = items.slice(0, 10).join(", ");
            const hidden = items.slice(10).join(", ");
            return visible + (items.length > 10 
                ? `<span class="voir-plus" onclick="this.nextElementSibling.style.display='inline'; this.style.display='none';">... Voir plus</span><span style="display:none">, ${hidden}</span>` 
                : '');
        };

        tableResults.innerHTML = `
            <div class="analysis-section">
                <h3 class="section-title">Incohérences détectées dans t_ebp</h3>
                <table class="analysis-table">
                    <thead><tr><th>Champ</th><th>Incohérences</th></tr></thead>
                     <tbody>
                     <tr><td>bp_code non uniques</td><td>${formatList(data.duplicated_bp_code)}</td></tr>
                      <tr><td>Taux d’unicité de bp_code</td><td>${data.bp_code_unicity_rate}%</td></tr>

                        <tr><td>bp_codeext</td><td>${formatList(data.invalid_bp_codeext)}</td></tr>
                        <tr><td>bp_pt_code</td><td>${formatList(data.invalid_bp_pt_code)}</td></tr>
                        <tr><td>Taux de remplissage bp_pt_code</td><td>${data.bp_pt_code_fill_rate}%</td></tr>
                        <tr><td>bp_prop</td><td>${formatList(data.invalid_bp_prop)}</td></tr>
                        <tr><td>bp_gest</td><td>${formatList(data.invalid_bp_gest)}</td></tr>
                        <tr><td>bp_user</td><td>${formatList(data.invalid_bp_user)}</td></tr>
                        <tr><td>bp_rf_code</td><td>${formatList(data.invalid_bp_rf_code)}</td></tr>
                        <tr><td>BPE sans cassette</td><td>${formatList(data.bpe_without_cassette)}</td></tr>
                        <!-- Ici on ajoute le nombre manquant / total entre parenthèses -->
                        <tr>
                        <td>Taux BPE sans cassette</td>
                        <td>
                            ${data.bpe_without_cassette_rate}% 
                            (${data.bpe_without_cassette.length}/${data.total_bp_count})
                        </td>
                        </tr>
                    </tbody>
                </table>
            </div>`;

        if (downloadCsvLink && data.csv_path) {
            downloadCsvLink.href = data.csv_path;
            downloadCsvLink.style.display = "inline-block";
            downloadCsvLink.textContent = "Télécharger CSV";
        }

        if (downloadHtmlLink && data.html_path) {
            downloadHtmlLink.href = data.html_path;
            downloadHtmlLink.style.display = "inline-block";
            downloadHtmlLink.textContent = "Télécharger HTML";
        }
    })
    .catch(error => {
        console.error("Erreur lors de l'analyse t_ebp :", error);
        errorContainer.innerHTML = `
            <div class="error-message">
                <strong>Erreur lors de l'analyse :</strong>
                <p>${error.message}</p>
            </div>
        `;
        tableResults.innerHTML = "";
    })
    .finally(() => {
        analyzeButton.disabled = false;
    });
}

// Écouteur de clic
document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('analyze-ebp');
    if (btn) {
        btn.addEventListener('click', runAnalysisEBP);
    }
});

//cohérence fibre
function runAnalysisFibreCable() {
    const exportDate = document.getElementById('export-date-single').value;
    if (!exportDate) { alert("Sélectionnez une date."); return; }
    const btn = document.getElementById('analyze-fibre-cable');
    const out = document.getElementById('table-results');
    const err = document.getElementById('error-container') || (() => {
      const d=document.createElement('div');d.id='error-container';
      document.getElementById('results-section').prepend(d);return d;
    })();
    btn.disabled=true; out.innerHTML="<div class='loading'>Analyse en cours...</div>"; err.innerHTML="";
  
    fetch('/analyze_fibre_cable',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({export_date:exportDate})
    })
    .then(r=>r.ok? r.json() : r.json().then(e=>{throw new Error(e.message)}))
    .then(data=>{
      if(data.status==='error') throw new Error(data.message);
      document.getElementById('analysis-title').textContent=
        `Analyse t_fibre → t_cable (${exportDate})`;
  
      const renderList = lst => {
        if(!lst||!lst.length) return "Aucune";
        let vis=lst.slice(0,10).join(", "), more=lst.slice(10);
        return vis + (more.length
          ? `<span class="voir-plus" onclick="this.nextElementSibling.style.display='inline';this.style.display='none';">... Voir plus</span>
             <span style="display:none">, ${more.join(", ")}</span>`
          : "");
      };
  
      out.innerHTML=`
      <div class="analysis-section">
          <h3>3. Unicité des fo_code</h3>
          <p>Total fibres : <strong>${data.total_fibres}</strong>,
             Codes uniques : <strong>${data.unique_fo_codes}</strong></p>
          <p>${renderList(data.fo_code_duplicates)}</p>
        </div>
        <div class="analysis-section">
          <h3>1. FO_CB_CODE</h3>
          <p>Total: <strong>${data.total_fo}</strong> – sans correspondance: <strong>${data.non_found_count}</strong></p>
          <p>${renderList(data.non_found_list)}</p>
        </div>
        <div class="analysis-section">
          <h3>2. Occurrences vs Capafo</h3>
          <p>Testés: <strong>${data.total_tested}</strong>
             Succès: <strong>${data.success_rate}%</strong>
             Échec: <strong>${data.failure_rate}%</strong>
          </p>
          <table class="analysis-table">
            <thead><tr><th>Code</th><th>Occ.</th><th>Capafo</th></tr></thead>
            <tbody>
              ${data.failures.slice(0,10).map(f=>`
                <tr><td>${f.code}</td><td>${f.occurrences}</td><td>${f.capafo}</td></tr>
              `).join('')}
              ${data.failures.length>10
                ? `<tr><td colspan=3>... ${data.failures.length-10} autres</td></tr>`
                : ''}
            </tbody>
          </table>
        </div>`;
  
      ['csv','html'].forEach(ext=>{
        const a=document.getElementById(`download-results-${ext}`);
        if(a) {
          a.href = data[`${ext}_path`];
          a.style.display = 'inline-block';
        }
      });
    })
    .catch(e=>{
      err.innerHTML=`<p class="error-message">Erreur: ${e.message}</p>`;
      out.innerHTML="";
    })
    .finally(()=>btn.disabled=false);
  }
  
  document.addEventListener('DOMContentLoaded',()=>{
    const btn=document.getElementById('analyze-fibre-cable');
    if(btn) btn.addEventListener('click',runAnalysisFibreCable);
  });
  
//cohérence table t_position
function runAnalysisPosition() {
    const exportDate = document.getElementById('export-date-single').value;
    if (!exportDate) { alert("Sélectionnez une date."); return; }
  
    const btn = document.getElementById('analyze-position');
    const out = document.getElementById('table-results');
    const err = document.getElementById('error-container') || (() => {
      const d=document.createElement('div'); d.id='error-container';
      document.getElementById('results-section').prepend(d);
      return d;
    })();
  
    btn.disabled = true;
    out.innerHTML = "<div class='loading'>Analyse en cours…</div>";
    err.innerHTML = "";
  
    fetch('/analyze_position', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({export_date: exportDate})
    })
    .then(r => r.ok ? r.json() : r.json().then(e=>{throw new Error(e.message)}))
    .then(data => {
      if (data.status === 'error') throw new Error(data.message);
      document.getElementById('analysis-title').textContent = 
        `Analyse position (${exportDate})`;
  
      const renderList = lst => {
        if (!lst || !lst.length) return "Aucun";
        let vis = lst.slice(0,10).join(", "), more = lst.slice(10);
        return vis + (more.length
          ? `<span class="voir-plus" onclick="this.nextElementSibling.style.display='inline';this.style.display='none';">... Voir plus</span>
             <span style="display:none">, ${more.join(", ")}</span>`
          : '');
      };
  
      out.innerHTML = `
       <div class="analysis-section">
          <h3>0. Unicité des ps_code</h3>
          <p>Total : <strong>${data.total_ps_code}</strong> — Uniques : <strong>${data.unique_ps_code}</strong></p>
          <table class="analysis-table">
            <thead><tr><th>ps_code</th><th>Occurrences</th></tr></thead>
            <tbody>
              ${data.duplicated_ps_code.slice(0, 10).map(row => 
                `<tr><td>${row.ps_code}</td><td>${row.count}</td></tr>`
              ).join('')}
              ${data.duplicated_ps_code.length > 10 
                ? '<tr><td colspan="2">... autres</td></tr>' 
                : ''}
            </tbody>
          </table>
        </div>
        <div class="analysis-section">
          <h3>1. Remplissage des champs</h3>
          <table class="analysis-table">
            <thead><tr><th>Champ</th><th>Remplis</th><th>Taux (%)</th></tr></thead>
            <tbody>
              <tr><td>ps_1</td><td>${data.fill_ps1}</td><td>${data.pct_ps1}%</td></tr>
              <tr><td>ps_2</td><td>${data.fill_ps2}</td><td>${data.pct_ps2}%</td></tr>
              <tr><td>ps_cs_code</td><td>${data.fill_cs}</td><td>${data.pct_cs}%</td></tr>
            </tbody>
          </table>
        </div>
  
        <div class="analysis-section">
          <h3>2. Existence dans t_fibre.fo_code</h3>
          <table class="analysis-table">
            <thead><tr><th>Champ</th><th>Valeurs manquantes</th></tr></thead>
            <tbody>
              <tr><td>ps_1</td><td>${renderList(data.missing_ps1)}</td></tr>
              <tr><td>ps_2</td><td>${renderList(data.missing_ps2)}</td></tr>
            </tbody>
          </table>
        </div>
  
        <div class="analysis-section">
        <h3>3. Existence dans t_cassette.cs_code</h3>
        <p>Total lignes : <strong>${data.total_rows}</strong> – 
            Manquants : <strong>${data.missing_cs_count}</strong> 
            (<strong>${data.missing_cs_pct}%</strong>)</p>
        <table class="analysis-table">
            <thead><tr><th>ps_cs_code manquants</th></tr></thead>
            <tbody>
            <tr><td>${renderList(data.missing_cs)}</td></tr>
            </tbody>
          </table>
        </div>`;
  
      ['csv','html'].forEach(ext=>{
        const a = document.getElementById(`download-results-${ext}`);
        if (a && data[`${ext}_path`]) {
          a.href = data[`${ext}_path`];
          a.style.display = 'inline-block';
        }
      });
    })
    .catch(e => {
      err.innerHTML = `<p class="error-message">Erreur : ${e.message}</p>`;
      out.innerHTML = "";
    })
    .finally(() => btn.disabled = false);
  }
  
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('analyze-position');
    if (btn) btn.addEventListener('click', runAnalysisPosition);
  });
  
//cohérence table t_ltech
function runAnalysisLTech() {
    const exportDate = document.getElementById('export-date-single')?.value;
    if (!exportDate) {
      alert("Veuillez sélectionner une date d'export.");
      return;
    }
  
    const btn = document.getElementById('analyze-ltech');
    const out = document.getElementById('table-results');
    const err = document.getElementById('error-container') || (() => {
      const d = document.createElement('div');
      d.id = 'error-container';
      document.getElementById('results-section').prepend(d);
      return d;
    })();
  
    btn.disabled = true;
    out.innerHTML = "<div class='loading'>Analyse en cours…</div>";
    err.innerHTML = "";
  
    fetch('/analyze_ltech', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({export_date: exportDate})
    })
    .then(resp => resp.ok ? resp.json() : resp.json().then(e => { throw new Error(e.message) }))
    .then(data => {
      if (data.status === 'error') throw new Error(data.message);
  
      document.getElementById('analysis-title').textContent =
        `Analyse t_ltech (${exportDate})`;
  
      const renderList = lst => {
        if (!lst?.length) return "Aucun";
        const vis = lst.slice(0,10).join(", ");
        const more = lst.slice(10);
        return vis + (more.length
          ? `<span class="voir-plus" onclick="this.nextElementSibling.style.display='inline';this.style.display='none';">... Voir plus</span>
             <span style="display:none">, ${more.join(", ")}</span>`
          : "");
      };
  
      out.innerHTML = `
      <div class="analysis-section">
          <h3>Unicité des lt_code</h3>
          <p>Total : <strong>${data.total_lt_code}</strong> — Uniques : <strong>${data.unique_lt_code}</strong></p>
          <table class="analysis-table">
            <thead><tr><th>lt_code</th><th>Occurrences</th></tr></thead>
            <tbody>
              ${data.duplicated_lt_code.slice(0, 10).map(row => 
                `<tr><td>${row.lt_code}</td><td>${row.count}</td></tr>`
              ).join('')}
              ${data.duplicated_lt_code.length > 10 
                ? '<tr><td colspan="2">... autres</td></tr>'
                : ''}
            </tbody>
          </table>
        </div>
        <div class="analysis-section">
          <h3>Manquants par champ</h3>
          <table class="analysis-table">
            <thead><tr><th>Champ</th><th>Manquants</th><th>%</th></tr></thead>
            <tbody>
            <tr><td>lt_st_code</td>
                <td>${data.st_missing_count}/${data.total_rows}</td>
                <td>${data.st_missing_pct}%</td></tr>
            <tr><td>lt_prop</td>
                <td>${data.prop_missing_count}/${data.total_rows}</td>
                <td>${data.prop_missing_pct}%</td></tr>
            <tr><td>lt_gest</td>
                <td>${data.gest_missing_count}/${data.total_rows}</td>
                <td>${data.gest_missing_pct}%</td></tr>
            <tr><td>lt_user</td>
                <td>${data.user_missing_count}/${data.total_rows}</td>
                <td>${data.user_missing_pct}%</td></tr>
            </tbody>

          </table>
        </div>
        <div class="analysis-section">
          <h3>Détails des manquants</h3>
          <table class="analysis-table">
            <thead><tr><th>Champ</th><th>Valeurs</th></tr></thead>
            <tbody>
              <tr><td>lt_st_code</td><td>${renderList(data.st_missing_list)}</td></tr>
              <tr><td>lt_prop</td><td>${renderList(data.prop_missing_list)}</td></tr>
              <tr><td>lt_gest</td><td>${renderList(data.gest_missing_list)}</td></tr>
              <tr><td>lt_user</td><td>${renderList(data.user_missing_list)}</td></tr>
            </tbody>
          </table>
        </div>`;
  
      ['csv','html'].forEach(ext => {
        const a = document.getElementById(`download-results-${ext}`);
        if (a && data[`${ext}_path`]) {
          a.href = data[`${ext}_path`];
          a.style.display = 'inline-block';
        }
      });
    })
    .catch(e => {
      err.innerHTML = `<p class="error-message">Erreur : ${e.message}</p>`;
      out.innerHTML = "";
    })
    .finally(() => btn.disabled = false);
  }
  
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('analyze-ltech');
    if (btn) btn.addEventListener('click', runAnalysisLTech);
  });
  
  //cohérence table t_ptech
  function runAnalysisPTech() {
    const exportDate = document.getElementById('export-date-single')?.value;
    if (!exportDate) { alert("Sélectionnez une date."); return; }
  
    const btn = document.getElementById('analyze-ptech');
    const out = document.getElementById('table-results');
    const err = document.getElementById('error-container') || (() => {
      const d=document.createElement('div'); d.id='error-container';
      document.getElementById('results-section').prepend(d);
      return d;
    })();
  
    btn.disabled = true;
    out.innerHTML = "<div class='loading'>Analyse en cours…</div>";
    err.innerHTML = "";
  
    fetch('/analyze_ptech', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({export_date: exportDate})
    })
    .then(r=> r.ok ? r.json() : r.json().then(e=>{throw new Error(e.message)}))
    .then(data=>{
      if (data.status==='error') throw new Error(data.message);
      document.getElementById('analysis-title').textContent =
        `Analyse t_ptech (${exportDate})`;
  
      const renderList = lst=>{
        if(!lst?.length) return "Aucun";
        let vis=lst.slice(0,10).join(", "), more=lst.slice(10);
        return vis + (more.length
          ? `<span class="voir-plus" onclick="this.nextElementSibling.style.display='inline';this.style.display='none';">... Voir plus</span>
             <span style="display:none">, ${more.join(", ")}</span>`
          : "");
      };
  
      out.innerHTML=`
              <div class="analysis-section">
          <h3>0. Unicité de pt_code</h3>
          <p>
            Total : <strong>${data.unicite_pt_code.total}</strong><br>
            Remplis : <strong>${data.unicite_pt_code.remplis}</strong><br>
            Uniques : <strong>${data.unicite_pt_code.uniques}</strong><br>
            Doublons : ${renderList(data.unicite_pt_code.doublons)}
          </p>
        </div>

        <div class="analysis-section">
          <h3>Résumé des tests</h3>
          <table class="analysis-table">
            <thead><tr><th>Test</th><th>Bad/Total</th><th>%</th></tr></thead>
            <tbody>
              <tr><td>PT_CODEEXT</td><td>${data.bad_ext_count}/${data.total}</td><td>${data.bad_ext_pct}%</td></tr>
              <tr><td>pt_nd_code</td><td>${data.nd_bad_count}/${data.total}</td><td>${data.nd_bad_pct}%</td></tr>
              <tr><td>pt_prop</td><td>${data.prop_cnt}/${data.total}</td><td>${data.prop_pct}%</td></tr>
              <tr><td>pt_gest</td><td>${data.gest_cnt}/${data.total}</td><td>${data.gest_pct}%</td></tr>
              <tr><td>pt_user</td><td>${data.user_cnt}/${data.total}</td><td>${data.user_pct}%</td></tr>
              <tr><td>pt_nature vides</td><td>${data.nat_empty}/${data.total}</td><td>${data.nat_pct}%</td></tr>
              <tr><td>pt_ad_code</td><td>${data.ad_bad_count}/${data.total}</td><td>${data.ad_bad_pct}%</td></tr>
            </tbody>
          </table>
        </div>
        <div class="analysis-section">
          <h3>Détails invalides</h3>
          <table class="analysis-table">
            <thead><tr><th>Test</th><th>Valeurs</th></tr></thead>
            <tbody>
              <tr><td>PT_CODEEXT</td><td>${renderList(data.bad_ext)}</td></tr>
              <tr><td>pt_nd_code</td><td>${renderList(data.nd_bad)}</td></tr>
              <tr><td>pt_prop</td><td>${renderList(data.prop_bad)}</td></tr>
              <tr><td>pt_gest</td><td>${renderList(data.gest_bad)}</td></tr>
              <tr><td>pt_user</td><td>${renderList(data.user_bad)}</td></tr>
              <tr><td>pt_ad_code</td><td>${renderList(data.ad_bad)}</td></tr>
            </tbody>
          </table>
        </div>`;
  
      ['csv','html'].forEach(ext=>{
        const a=document.getElementById(`download-results-${ext}`);
        if(a && data[`${ext}_path`]){
          a.href = data[`${ext}_path`];
          a.style.display = 'inline-block';
        }
      });
    })
    .catch(e=>{
      err.innerHTML = `<p class="error-message">Erreur : ${e.message}</p>`;
      out.innerHTML = "";
    })
    .finally(()=> btn.disabled=false);
  }
  
  document.addEventListener('DOMContentLoaded', ()=>{
    const btn = document.getElementById('analyze-ptech');
    if(btn) btn.addEventListener('click', runAnalysisPTech);
  });
  
//coherence table t_ropt
function runAnalysisROpt() {
  const exportDate = document.getElementById('export-date-single')?.value;
  if (!exportDate) {
    alert("Sélectionnez une date.");
    return;
  }

  const btn = document.getElementById('analyze-ropt');
  const out = document.getElementById('table-results');
  const err = document.getElementById('error-container') || (() => {
    const d = document.createElement('div');
    d.id = 'error-container';
    document.getElementById('results-section').prepend(d);
    return d;
  })();

  btn.disabled = true;
  out.innerHTML = "<div class='loading'>Analyse en cours…</div>";
  err.innerHTML = "";

  fetch('/analyze_ropt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ export_date: exportDate })
  })
    .then(r => r.ok ? r.json() : r.json().then(e => { throw new Error(e.message) }))
    .then(data => {
      if (data.status === 'error') throw new Error(data.message);

      document.getElementById('analysis-title').textContent =
        `Analyse t_ropt (${exportDate})`;

      const renderList = lst => {
        if (!lst?.length) return "Aucun";
        let vis = lst.slice(0, 10).join(", "), more = lst.slice(10);
        return vis + (more.length
          ? `<span class="voir-plus" onclick="this.nextElementSibling.style.display='inline';this.style.display='none';">... Voir plus</span>
             <span style="display:none">, ${more.join(", ")}</span>`
          : '');
      };

      out.innerHTML = `
        <table class="analysis-table">
          <thead>
            <tr>
              <th>Test</th>
              <th>Résultat</th>
              <th>Détails</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>1) Unicité de rt_id</td>
              <td>${data.unique_rt_id}/${data.total_rows} (${(100 - data.duplicate_pct).toFixed(2)}%)</td>
              <td>Doublons : ${data.duplicate_count} (${data.duplicate_pct}%)</td>
            </tr>
            <tr>
              <td>2) rt_fo_code → t_fibre.fo_code</td>
              <td>${data.fo_missing_count}/${data.total_rows} (${data.fo_missing_pct}%)</td>
              <td>${renderList(data.fo_missing)}</td>
            </tr>
            <tr>
              <td>3) rt_code_ext rempli</td>
              <td>${data.filled_ext}/${data.total_rows} (${data.fill_ext_pct}%)</td>
              <td>–</td>
            </tr>
            <tr>
              <td>4) Conflits multiples rt_code/rt_code_ext</td>
              <td>${data.conflict_count}/${data.total_rows} (${data.conflict_pct}%)</td>
              <td>${renderList(data.code_conflicts)}</td>
            </tr>
          </tbody>
        </table>
      `;

      ['csv', 'html'].forEach(ext => {
        const a = document.getElementById(`download-results-${ext}`);
        if (a && data[`${ext}_path`]) {
          a.href = data[`${ext}_path`];
          a.style.display = 'inline-block';
        }
      });
    })
    .catch(e => {
      err.innerHTML = `<p class="error-message">Erreur : ${e.message}</p>`;
      out.innerHTML = "";
    })
    .finally(() => btn.disabled = false);
}

  document.addEventListener('DOMContentLoaded', ()=>{
    const btn = document.getElementById('analyze-ropt');
    if(btn) btn.addEventListener('click', runAnalysisROpt);
  });
  
  //coherence t_sitetech
  function runAnalysisSiteTech() {
    const exportDate = document.getElementById('export-date-single')?.value;
    if (!exportDate) { alert("Sélectionnez une date."); return; }
  
    const btn = document.getElementById('analyze-sitetech');
    const out = document.getElementById('table-results');
    const err = document.getElementById('error-container') || (() => {
      const d = document.createElement('div'); d.id='error-container';
      document.getElementById('results-section').prepend(d);
      return d;
    })();
  
    btn.disabled = true;
    out.innerHTML = "<div class='loading'>Analyse en cours...</div>";
    err.innerHTML = "";
  
    fetch('/analyze_sitetech', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({export_date:exportDate})
    })
    .then(r => r.ok ? r.json() : r.json().then(e => { throw new Error(e.message); }))
    .then(data => {
      if (data.status === 'error') throw new Error(data.message);
      document.getElementById('analysis-title').textContent =
        `Analyse t_sitetech (${exportDate})`;
  
      const renderList = lst => {
        if (!lst?.length) return "Aucun";
        let vis = lst.slice(0,10).join(", "), more = lst.slice(10);
        return vis + (more.length
          ? `<span class="voir-plus" onclick="this.nextElementSibling.style.display='inline';this.style.display='none';">... Voir plus</span>
             <span style="display:none">, ${more.join(", ")}</span>`
          : '');
      };
  
      out.innerHTML = `
      <table class="analysis-table">
        <thead>
          <tr><th>Analyse d’unicité sur st_code</th><th>Valeur</th></tr>
        </thead>
        <tbody>
          <tr><td>Total de lignes</td><td>${data.total_rows}</td></tr>
          <tr><td>Codes uniques</td><td>${data.unique_st_code} (${data.unique_pct}%)</td></tr>
          <tr><td>Doublons</td><td>${data.duplicate_count} (${data.duplicate_pct}%)</td></tr>
        </tbody>
      </table><br>

        <table class="analysis-table">
          <thead>
            <tr><th>Test</th><th>Manquants/Total</th><th>%</th></tr>
          </thead>
          <tbody>
            <tr><td>st_nd_code</td>
                <td>${data.nd_miss_cnt}/${data.total_rows}</td>
                <td>${data.nd_miss_pct}%</td></tr>
            <tr><td>st_prop</td>
                <td>${data.prop_miss_cnt}/${data.total_rows}</td>
                <td>${data.prop_miss_pct}%</td></tr>
            <tr><td>st_gest</td>
                <td>${data.gest_miss_cnt}/${data.total_rows}</td>
                <td>${data.gest_miss_pct}%</td></tr>
          </tbody>
        </table>
        <h3>Détails des valeurs manquantes</h3>
        <table class="analysis-table">
          <thead><tr><th>Champ</th><th>Valeurs</th></tr></thead>
          <tbody>
            <tr><td>st_nd_code</td><td>${renderList(data.nd_missing)}</td></tr>
            <tr><td>st_prop</td><td>${renderList(data.prop_missing)}</td></tr>
            <tr><td>st_gest</td><td>${renderList(data.gest_missing)}</td></tr>
          </tbody>
        </table>`;
  
      ['csv','html'].forEach(ext => {
        const a = document.getElementById(`download-results-${ext}`);
        if (a && data[`${ext}_path`]) {
          a.href = data[`${ext}_path`];
          a.style.display = 'inline-block';
        }
      });
    })
    .catch(e => {
      err.innerHTML = `<p class="error-message">Erreur : ${e.message}</p>`;
      out.innerHTML = "";
    })
    .finally(() => btn.disabled = false);
  }
  
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('analyze-sitetech');
    if (btn) btn.addEventListener('click', runAnalysisSiteTech);
  });

//coherence t_suf
function runAnalysisSuf() {
    const exportDate = document.getElementById('export-date-single')?.value;
    if (!exportDate) { alert("Sélectionnez une date."); return; }
  
    const btn = document.getElementById('analyze-suf');
    const out = document.getElementById('table-results');
    const err = document.getElementById('error-container') || (() => {
      const d=document.createElement('div'); d.id='error-container';
      document.getElementById('results-section').prepend(d);
      return d;
    })();
  
    btn.disabled = true;
    out.innerHTML = "<div class='loading'>Analyse en cours…</div>";
    err.innerHTML = "";
  
    fetch('/analyze_suf', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({export_date: exportDate})
    })
    .then(r => r.ok ? r.json() : r.json().then(e=>{throw new Error(e.message)}))
    .then(data => {
      if (data.status==='error') throw new Error(data.message);
      document.getElementById('analysis-title').textContent =
        `Analyse t_suf (${exportDate})`;
  
      const renderList = lst => {
        if (!lst?.length) return "Aucun";
        const vis = lst.slice(0,10).join(", "), more = lst.slice(10);
        return vis + (more.length
          ? `<span class="voir-plus" onclick="this.nextElementSibling.style.display='inline';this.style.display='none';">... Voir plus</span>
             <span style="display:none">, ${more.join(", ")}</span>`
          : '');
      };
  
      out.innerHTML = `
      <tr><td>sf_code (unicité)</td>
    <td>${data.unique_sf_code}/${data.total_rows}</td>
    <td>${data.unique_pct}%</td></tr>

      
        <table class="analysis-table">
          <thead>
            <tr><th>Test</th><th>Manquants/Total</th><th>%</th></tr>
          </thead>
          <tbody>
            <tr><td>sf_nd_code</td>
                <td>${data.nd_miss_cnt}/${data.total_rows}</td>
                <td>${data.nd_miss_pct}%</td></tr>
            <tr><td>sf_ad_code</td>
                <td>${data.ad_miss_cnt}/${data.total_rows}</td>
                <td>${data.ad_miss_pct}%</td></tr>
            <tr><td>sf_oper</td>
                <td>${data.oper_miss_cnt}/${data.total_rows}</td>
                <td>${data.oper_miss_pct}%</td></tr>
            <tr><td>sf_prop</td>
                <td>${data.prop_miss_cnt}/${data.total_rows}</td>
                <td>${data.prop_miss_pct}%</td></tr>
          </tbody>
        </table>
        <h3>Détails des valeurs manquantes</h3>
        <table class="analysis-table">
          <thead><tr><th>Champ</th><th>Valeurs</th></tr></thead>
          <tbody>
            <tr><td>sf_nd_code</td><td>${renderList(data.nd_missing)}</td></tr>
            <tr><td>sf_ad_code</td><td>${renderList(data.ad_missing)}</td></tr>
            <tr><td>sf_oper</td><td>${renderList(data.oper_missing)}</td></tr>
            <tr><td>sf_prop</td><td>${renderList(data.prop_missing)}</td></tr>
          </tbody>
        </table>`;
  
      ['csv','html'].forEach(ext=>{
        const a=document.getElementById(`download-results-${ext}`);
        if(a && data[`${ext}_path`]){
          a.href = data[`${ext}_path`];
          a.style.display = 'inline-block';
        }
      });
    })
    .catch(e=>{
      err.innerHTML = `<p class="error-message">Erreur : ${e.message}</p>`;
      out.innerHTML = "";
    })
    .finally(()=>btn.disabled=false);
  }
  
  document.addEventListener('DOMContentLoaded', ()=>{
    const btn = document.getElementById('analyze-suf');
    if (btn) btn.addEventListener('click', runAnalysisSuf);
  });

//coherence t_tiroir
function runAnalysisTiroir() {
    const exportDate = document.getElementById('export-date-single')?.value;
    if (!exportDate) { alert("Sélectionnez une date."); return; }
  
    const btn = document.getElementById('analyze-tiroir');
    const out = document.getElementById('table-results');
    const err = document.getElementById('error-container') || (() => {
      const d = document.createElement('div'); d.id='error-container';
      document.getElementById('results-section').prepend(d);
      return d;
    })();
  
    btn.disabled = true;
    out.innerHTML = "<div class='loading'>Analyse en cours…</div>";
    err.innerHTML = "";
  
    fetch('/analyze_tiroir', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({export_date: exportDate})
    })
    .then(r => r.ok ? r.json() : r.json().then(e => { throw new Error(e.message); }))
    .then(data => {
      if (data.status === 'error') throw new Error(data.message);
      document.getElementById('analysis-title').textContent =
        `Analyse t_tiroir (${exportDate})`;
  
      const renderList = lst => {
        if (!lst?.length) return "Aucun";
        const vis = lst.slice(0,10).join(", "), more = lst.slice(10);
        return vis + (more.length
          ? `<span class="voir-plus" onclick="this.nextElementSibling.style.display='inline';this.style.display='none';">... Voir plus</span><span style="display:none">, ${more.join(", ")}</span>`
          : '');
      };
  
      out.innerHTML = `
      <tr><td>ti_code (unicité)</td>
    <td>${data.ti_code_unique}/${data.total_rows}</td>
    <td>${data.ti_code_unique_pct}%</td></tr>

        <table class="analysis-table">
          <thead><tr><th>Test</th><th>Manquants/Total</th><th>%</th></tr></thead>
          <tbody>
            <tr><td>ti_ba_code</td><td>${data.ba_cnt}/${data.total_rows}</td><td>${data.ba_pct}%</td></tr>
            <tr><td>ti_rf_code</td><td>${data.rf_cnt}/${data.total_rows}</td><td>${data.rf_pct}%</td></tr>
            <tr><td>ti_prop</td><td>${data.prop_cnt}/${data.total_rows}</td><td>${data.prop_pct}%</td></tr>
          </tbody>
        </table>
        <h3>Détails des valeurs manquantes</h3>
        <table class="analysis-table">
          <thead><tr><th>Champ</th><th>Valeurs</th></tr></thead>
          <tbody>
            <tr><td>ti_ba_code</td><td>${renderList(data.ba_missing)}</td></tr>
            <tr><td>ti_rf_code</td><td>${renderList(data.rf_missing)}</td></tr>
            <tr><td>ti_prop</td><td>${renderList(data.prop_missing)}</td></tr>
          </tbody>
        </table>`;
  
      ['csv','html'].forEach(ext => {
        const a = document.getElementById(`download-results-${ext}`);
        if (a && data[`${ext}_path`]) {
          a.href = data[`${ext}_path`];
          a.style.display = 'inline-block';
        }
      });
    })
    .catch(e => {
      err.innerHTML = `<p class="error-message">Erreur : ${e.message}</p>`;
      out.innerHTML = "";
    })
    .finally(() => btn.disabled = false);
  }
  
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('analyze-tiroir');
    if (btn) btn.addEventListener('click', runAnalysisTiroir);
  });

  
//cohérence t_cableline
function runAnalysisCableLine() {
    const exportDate = document.getElementById('export-date-single')?.value;
    if (!exportDate) { alert("Sélectionnez une date."); return; }
  
    const btn = document.getElementById('analyze-cableline');
    const out = document.getElementById('table-results');
    const err = document.getElementById('error-container') || (() => {
      const d = document.createElement('div'); d.id='error-container';
      document.getElementById('results-section').prepend(d);
      return d;
    })();
  
    btn.disabled = true;
    out.innerHTML = "<div class='loading'>Analyse en cours…</div>";
    err.innerHTML = "";
  
    fetch('/analyze_cableline', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({export_date: exportDate})
    })
    .then(r => r.ok ? r.json() : r.json().then(e => { throw new Error(e.message); }))
    .then(data => {
      if (data.status === 'error') throw new Error(data.message);
      document.getElementById('analysis-title').textContent =
        `Analyse t_cableline (${exportDate})`;
  
      const renderList = lst => {
        if (!lst?.length) return "Aucun";
        const vis = lst.slice(0,10).join(", "), more = lst.slice(10);
        return vis + (more.length
          ? `<span class="voir-plus" onclick="this.nextElementSibling.style.display='inline';this.style.display='none';">... Voir plus</span><span style="display:none">, ${more.join(", ")}</span>`
          : '');
      };
  
      out.innerHTML = `
      <tr><td>cl_code (unicité)</td>
    <td>${data.unique_cl_code}/${data.total_rows}</td>
    <td>${data.unique_pct}%</td></tr>

        <table class="analysis-table">
          <thead><tr><th>Test</th><th>Manquants/Total</th><th>%</th></tr></thead>
          <tbody>
            <tr><td>cl_cb_code</td>
                <td>${data.miss_cnt}/${data.total_rows}</td>
                <td>${data.miss_pct}%</td></tr>
          </tbody>
        </table>
        <h3>Détails des valeurs manquantes</h3>
        <table class="analysis-table">
          <thead><tr><th>Champ</th><th>Valeurs</th></tr></thead>
          <tbody>
            <tr><td>cl_cb_code</td><td>${renderList(data.missing)}</td></tr>
          </tbody>
        </table>`;
  
      ['csv','html'].forEach(ext => {
        const a = document.getElementById(`download-results-${ext}`);
        if (a && data[`${ext}_path`]) {
          a.href = data[`${ext}_path`];
          a.style.display = 'inline-block';
        }
      });
    })
    .catch(e => {
      err.innerHTML = `<p class="error-message">Erreur : ${e.message}</p>`;
      out.innerHTML = "";
    })
    .finally(() => btn.disabled = false);
  }
  
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('analyze-cableline');
    if (btn) btn.addEventListener('click', runAnalysisCableLine);
  });
  
//coherence t_noeud
function runAnalysisNoeud() {
    const exportDate = document.getElementById('export-date-single')?.value;
    if (!exportDate) { alert("Sélectionnez une date."); return; }
  
    const btn = document.getElementById('analyze-noeud');
    const out = document.getElementById('table-results');
    const err = document.getElementById('error-container') || (() => {
      const d = document.createElement('div'); d.id = 'error-container';
      document.getElementById('results-section').prepend(d);
      return d;
    })();
  
    btn.disabled = true;
    out.innerHTML = "<div class='loading'>Analyse en cours…</div>";
    err.innerHTML = "";
  
    fetch('/analyze_noeud', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({export_date: exportDate})
    })
    .then(r => r.ok ? r.json() : r.json().then(e => { throw new Error(e.message); }))
    .then(data => {
      if (data.status === 'error') throw new Error(data.message);
      document.getElementById('analysis-title').textContent =
        `Analyse t_noeud (${exportDate})`;
  
      const renderList = lst => {
        if (!lst?.length) return "Aucun";
        const vis = lst.slice(0,10).join(", "), more = lst.slice(10);
        return vis + (more.length
          ? `<span class="voir-plus" onclick="this.nextElementSibling.style.display='inline';this.style.display='none';">... Voir plus</span><span style="display:none">, ${more.join(", ")}</span>`
          : '');
      };
  
      out.innerHTML = `
      <tr><td>nd_code (unicité)</td>
          <td>${data.unique_nd_code}/${data.total_rows}</td>
          <td>${data.unique_pct}%</td></tr>
        <h3>Codes nd_code dupliqués</h3>
<p>${renderList(data.duplicates)}</p>


        <table class="analysis-table">
          <thead><tr><th>Test</th><th>Manquants/Total</th><th>%</th></tr></thead>
          <tbody>
          
            <tr><td>nd_codeext</td>
                <td>${data.miss_count}/${data.total_rows}</td>
                <td>${data.miss_pct}%</td></tr>
          </tbody>
        </table>
        <h3>Détails des valeurs invalides</h3>
        <table class="analysis-table">
          <thead><tr><th>Champ</th><th>Valeurs</th></tr></thead>
          <tbody>
            <tr><td>nd_codeext</td><td>${renderList(data.missing)}</td></tr>
          </tbody>
        </table>`;
  
      ['csv','html'].forEach(ext => {
        const a = document.getElementById(`download-results-${ext}`);
        if (a && data[`${ext}_path`]) {
          a.href = data[`${ext}_path`];
          a.style.display = 'inline-block';
        }
      });
    })
    .catch(e => {
      err.innerHTML = `<p class="error-message">Erreur : ${e.message}</p>`;
      out.innerHTML = "";
    })
    .finally(() => btn.disabled = false);
  }
  
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('analyze-noeud');
    if (btn) btn.addEventListener('click', runAnalysisNoeud);
  });
  
//coherence t_cheminement
function runAnalysisCheminement() {
    const exportDate = document.getElementById('export-date-single')?.value;
    if (!exportDate) { alert("Sélectionnez une date."); return; }
  
    const btn = document.getElementById('analyze-cheminement');
    const out = document.getElementById('table-results');
    const err = document.getElementById('error-container') || (() => {
      const d=document.createElement('div'); d.id='error-container';
      document.getElementById('results-section').prepend(d);
      return d;
    })();
  
    btn.disabled = true;
    out.innerHTML = "<div class='loading'>Analyse en cours…</div>";
    err.innerHTML = "";
  
    fetch('/analyze_cheminement', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({export_date: exportDate})
    })
    .then(r => r.ok ? r.json() : r.json().then(e=>{throw new Error(e.message)}))
    .then(data => {
      if (data.status==='error') throw new Error(data.message);
      document.getElementById('analysis-title').textContent =
        `Analyse t_cheminement (${exportDate})`;
  
      const renderList = lst => {
        if (!lst?.length) return "Aucun";
        const vis = lst.slice(0,10).join(", "), more = lst.slice(10);
        return vis + (more.length
          ? `<span class="voir-plus" onclick="this.nextElementSibling.style.display='inline';this.style.display='none';">... Voir plus</span>
             <span style="display:none">, ${more.join(", ")}</span>`
          : '');
      };
  
      out.innerHTML = `
        <table class="analysis-table">
          <thead>
            <tr>
              <th>Test</th><th>Remplis/Total (%)</th><th>Invalids/Total (%)</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>cm_ndcode1</td>
              <td>${data.f1}/${data.total_rows} (${data.p1}%)</td>
              <td>${data.c1}/${data.total_rows} (${data.q1}%)</td>
            </tr>
            <tr>
              <td>cm_ndcode2</td>
              <td>${data.f2}/${data.total_rows} (${data.p2}%)</td>
              <td>${data.c2}/${data.total_rows} (${data.q2}%)</td>
            </tr>
            <tr>
              <td>cm_gest_do</td>
              <td>–</td>
              <td>${data.cg}/${data.total_rows} (${data.pg}%)</td>
            </tr>
            <tr>
              <td>cm_prop_do</td>
              <td>–</td>
              <td>${data.cp}/${data.total_rows} (${data.pp}%)</td>
            </tr>
            <tr>
              <td>cm_codeext</td>
              <td>–</td>
              <td>${data.cnt_ce}/${data.total_rows} (${data.pct_ce}%)</td>
            </tr>

          </tbody>
        </table>

          <h3>Unicité de cm_code</h3>
          <table class="analysis-table">
            <thead><tr><th>Total</th><th>Taux (%)</th><th>Doublons</th></tr></thead>
            <tbody>
              <tr>
                <td>${data.total_cm}</td>
                <td>${data.cm_code_unique_rate}%</td>
                <td>${renderList(data.duplicated_cm_code)}</td>
              </tr>
            </tbody>
          </table>
  
        <h3>Détails des valeurs invalides</h3>
        <table class="analysis-table">
          <thead><tr><th>Champ</th><th>Valeurs</th></tr></thead>
          <tbody>
            <tr><td>cm_ndcode1</td><td>${renderList(data.m1)}</td></tr>
            <tr><td>cm_ndcode2</td><td>${renderList(data.m2)}</td></tr>
            <tr><td>cm_gest_do</td><td>${renderList(data.mg)}</td></tr>
            <tr><td>cm_prop_do</td><td>${renderList(data.mp)}</td></tr>
            <tr><td>cm_codeext</td><td>${renderList(data.missing_ce)}</td></tr>
          </tbody>
        </table>`;
        
  
      ['csv','html'].forEach(ext=>{
        const a = document.getElementById(`download-results-${ext}`);
        if (a && data[`${ext}_path`]) {
          a.href = data[`${ext}_path`];
          a.style.display = 'inline-block';
        }
      });
    })
    .catch(e => {
      err.innerHTML = `<p class="error-message">Erreur : ${e.message}</p>`;
      out.innerHTML = "";
    })
    .finally(() => btn.disabled = false);
  }
  
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('analyze-cheminement');
    if (btn) btn.addEventListener('click', runAnalysisCheminement);
  });
  

//super bouton
function runAllAnalyses() {
    const exportDate = document.getElementById('export-date-single').value;
    const loadingIndicator = document.getElementById('loading-indicator-analyze-all');
    const resultsContainer = document.getElementById('results-single');
    
    if (!exportDate) {
        alert("Veuillez sélectionner une date d'export.");
        return;
    }

    loadingIndicator.style.display = 'inline';
    resultsContainer.innerHTML = "<p>Analyse globale en cours... Cela peut prendre du temps.</p>";

    fetch('/analyze_all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ export_date: exportDate })
    })
    .then(response => {
        if (!response.ok) throw new Error("Erreur serveur");
        return response.json();
    })
    .then(data => {
        resultsContainer.innerHTML = `
            <h3>Analyse complète terminée.</h3>
            <p>Vous pouvez télécharger tous les résultats ici :</p>
            <a href="${data.zip_path}" class="btn-download">Télécharger le fichier ZIP</a>
        `;
    })
    .catch(error => {
        console.error("Erreur analyse globale :", error);
        resultsContainer.innerHTML = `<p style="color: red;">Erreur : ${error.message}</p>`;
    })
    .finally(() => {
        loadingIndicator.style.display = 'none';
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const analyzeAllBtn = document.getElementById('analyze-all-btn');
    if (analyzeAllBtn) {
        analyzeAllBtn.addEventListener('click', runAllAnalyses);
    }
});

document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('form-analyze-all');
    const exportDateField = document.getElementById('export-date-single');
    const hiddenField = document.getElementById('hidden-export-date-analyze-all');
    const loading = document.getElementById('loading-indicator-analyze-all');
    const resultsContainer = document.getElementById('results-single');

    form.addEventListener('submit', function (event) {
        event.preventDefault(); // Empêche l’envoi classique du formulaire

        const exportDate = exportDateField.value;
        if (!exportDate) {
            alert("Veuillez sélectionner une date d'export.");
            return;
        }

        hiddenField.value = exportDate;
        loading.style.display = "inline";
        resultsContainer.innerHTML = "<p>Analyse globale en cours, merci de patienter…</p>";

        fetch('/analyze_all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ export_date: exportDate })
        })
        .then(response => {
            if (!response.ok) throw new Error("Erreur lors de l'analyse globale.");
            return response.json();
        })
        .then(data => {
            resultsContainer.innerHTML = `
                <h3>Analyse complète terminée.</h3>
                <a href="${data.zip_path}" class="btn-download btn-download-green">
                    Télécharger les Résultats (.zip)
                </a>
            `;
        })
        .catch(error => {
            console.error("Erreur analyse tout :", error);
            resultsContainer.innerHTML = `<p style="color: red;">Erreur : ${error.message}</p>`;
        })
        .finally(() => {
            loading.style.display = "none";
        });
    });
});

//history bouton
function toggleExportHistory() {
    const panel = document.getElementById('export-history-panel');
    const toggleBtn = document.querySelector('.accordion-toggle');

    panel.classList.toggle('open');

    if (panel.classList.contains('open')) {
        toggleBtn.innerText = "Exports déjà disponibles ▴";
    } else {
        toggleBtn.innerText = "Exports déjà disponibles ▾";
    }
}

function fetchExportHistory() {
    fetch('/liste_exports')
        .then(response => response.json())
        .then(data => {
            const historyList = document.getElementById('export-history-list');
            historyList.innerHTML = '';

            if (data.dates && data.dates.length > 0) {
                data.dates.forEach(date => {
                    const li = document.createElement('li');
                    li.textContent = `• ${date}`;
                    historyList.appendChild(li);
                });
            } else {
                const li = document.createElement('li');
                li.textContent = "Aucun export encore disponible.";
                historyList.appendChild(li);
            }
        })
        .catch(err => {
            console.error("Erreur lors de la récupération des exports :", err);
        });
}

document.addEventListener('DOMContentLoaded', fetchExportHistory);
