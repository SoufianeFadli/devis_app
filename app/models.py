<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Devis SBBM - Formulaire</title>
  <link rel="stylesheet" href="/static/style.css">
  <link rel="icon" href="/static/favicon.ico">
  <style>
    .hidden { display: none; }
    .zone-block { border: 1px solid #ccc; padding: 10px; border-radius: 6px; margin-top: 10px; }
    .zone-title { font-weight: bold; margin-bottom: 8px; }
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 10px; }
    .table-like { width: 100%; border-collapse: collapse; margin-top: 5px; }
    .table-like th, .table-like td { border: 1px solid #ccc; padding: 4px; font-size: 12px; }
    .btn-small { font-size: 12px; padding: 3px 8px; margin-top: 4px; }
    .radio-group { display: flex; gap: 12px; flex-wrap: wrap; }
    .hint { font-size: 11px; color: #555; }
    .row-flex { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  </style>
</head>
<body>
  <div class="page">
    <header class="header">
      <div class="header-left">
        <div class="societe">SOCIÉTÉ DE BÂTIMENTS ET BÉTON MOULÉ “SBBM”</div>
        <div class="coord">
          Lot 410 Sidi Ghanem Q.I Marrakech<br>
          Tél : +212 5 24 33 54 48 • Email : sbbmdga@gmail.com
        </div>
      </div>
      <div class="header-right">
        <div class="logo-box">
          <img src="/static/logo_sbbm.jpg" alt="Logo SBBM">
        </div>
      </div>
    </header>

    <div class="title">Formulaire de saisie — Génération Devis</div>

    <form class="form" action="/generate" method="post" enctype="multipart/form-data">
      <!-- ================== Infos client & devis ================== -->
      <div class="top-grid">
        <div class="card">
          <div class="card-title">INFORMATIONS CLIENT</div>
          <div class="grid2">
            <label class="lbl">Code client</label>
            <input class="inp" name="code_client" placeholder="ex: 34210..." />

            <label class="lbl">Client *</label>
            <input class="inp" name="client" required placeholder="Nom client" />

            <label class="lbl">Adresse chantier *</label>
            <input class="inp" name="chantier" required placeholder="Chantier / adresse" />

            <label class="lbl">Niveau</label>
            <input class="inp" name="niveau" placeholder="ex: R+2" />

            <label class="lbl">N° affaire</label>
            <input class="inp" name="affaire" placeholder="Optionnel" />
          </div>
        </div>

        <div class="card">
          <div class="card-title">INFORMATIONS DEVIS</div>
          <div class="grid2">
            <label class="lbl">Date devis</label>
            <input class="inp" name="date_devis" value="{{ today }}" />

            <label class="lbl">Réf devis *</label>
            <input class="inp" name="ref_devis" required placeholder="ex: jan-25" />

            <label class="lbl">Mode livraison</label>
            <select class="inp" name="mode_livraison">
              <option value="SOLO">SOLO</option>
              <option value="REMORQUE">REMORQUE</option>
            </select>

            <label class="lbl">Distance (km)</label>
            <input class="inp" name="distance_km" type="number" step="0.1" value="0" />

            <label class="lbl">Validité</label>
            <input class="inp" name="validite" value="30 jours" />
          </div>
        </div>
      </div>

      <!-- ================== Commercial & remises ================== -->
      <div class="card" style="margin-top:12px;">
        <div class="card-title">COMMERCIAL & REMISES</div>
        <div class="grid2">
          <label class="lbl">Code commercial</label>
          <select class="inp" name="code_commercial" id="code_commercial">
            {% for code, nom in liste_commerciaux.items() %}
            <option value="{{ code }}">{{ code }} - {{ nom }}</option>
            {% endfor %}
          </select>

          <label class="lbl">Nom commercial</label>
          <input class="inp" id="nom_commercial" name="nom_commercial" readonly />

          <label class="lbl">Remise poutrelles (%)</label>
          <input class="inp" type="number" step="0.01" name="remise_poutrelle" value="30" />

          <label class="lbl">Remise hourdis (%)</label>
          <input class="inp" type="number" step="0.01" name="remise_hourdis" value="25" />

          <label class="lbl">Prix unitaire contrôle technique (DH)</label>
          <input class="inp" type="number" step="0.01" name="prix_ct" value="3" />

          <label class="lbl">Prix unitaire treillis soudés (DH)</label>
          <input class="inp" type="number" step="0.01" name="prix_treillis" value="160" />
        </div>
      </div>

      <!-- ================== Choix mode de saisie ================== -->
      <div class="card" style="margin-top:12px;">
        <div class="card-title">MODE DE SAISIE DES QUANTITÉS</div>
        <div class="radio-group">
          <label>
            <input type="radio" name="saisie_mode" value="progiciel" id="mode_progiciel" checked>
            À partir du fichier progiciel (CSV)
          </label>
          <label>
            <input type="radio" name="saisie_mode" value="manuel" id="mode_manuel">
            Saisie manuelle des poutrelles / hourdis / CT / treillis
          </label>
        </div>

        <!-- Zone fichier progiciel -->
        <div id="zone_progiciel" class="zone-block" style="margin-top:10px;">
          <div class="zone-title">FICHIER PROGICIEL (CSV)</div>
          <div class="grid2">
            <div class="lbl">Importer le CSV</div>
            <input class="inp" type="file" name="fichier_progiciel" accept=".csv,text/csv" />
            <div class="hint">Si vide, le système génère un devis sans quantités.</div>
          </div>
        </div>

        <!-- Zone saisie manuelle -->
        <div id="zone_manuel" class="zone-block hidden" style="margin-top:10px;">
          <div class="zone-title">SAISIE MANUELLE</div>

          <!-- POUTRELLES -->
          <div>
            <div class="zone-title">Poutrelles</div>
            <table class="table-like" id="table_poutrelles">
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Longueur (ml)</th>
                  <th>Nb étriers / poutrelle</th>
                  <th>Nombre de poutrelles</th>
                  <th></th>
                </tr>
              </thead>
              <tbody id="tbody_poutrelles">
                <!-- Lignes ajoutées en JS -->
              </tbody>
            </table>
            <button type="button" class="btn btn-small" id="btn_add_poutrelle">+ Ajouter poutrelle</button>
          </div>

          <!-- HOURDIS -->
          <div style="margin-top:10px;">
            <div class="zone-title">Hourdis</div>
            <table class="table-like" id="table_hourdis">
              <thead>
                <tr>
                  <th>Type hourdis</th>
                  <th>Quantité (unités)</th>
                  <th></th>
                </tr>
              </thead>
              <tbody id="tbody_hourdis">
                <!-- Lignes ajoutées en JS -->
              </tbody>
            </table>
            <button type="button" class="btn btn-small" id="btn_add_hourdis">+ Ajouter hourdis</button>
          </div>

          <!-- CT & TREILLIS -->
          <div style="margin-top:10px;" class="grid2">
            <div>
              <label class="lbl">Surface contrôle technique (m²)</label>
              <input class="inp" type="number" step="0.01" name="surface_ct_manual" value="0">
            </div>
            <div>
              <label class="lbl">Nombre de treillis soudés</label>
              <input class="inp" type="number" step="1" name="nb_treillis_manual" value="0">
            </div>
          </div>
        </div>
      </div>

      <!-- ================== Transport ================== -->
      <div class="card" style="margin-top:12px;">
        <div class="card-title">TRANSPORT</div>

        <div class="grid2">
          <div>
            <label class="lbl">Mode transport</label>
            <select class="inp" name="mode_transport" id="mode_transport">
              <option value="depart">Départ usine</option>
              <option value="rendu">Rendu chantier</option>
            </select>
          </div>

          <div>
            <label class="lbl">Mode de calcul du transport</label>
            <div class="radio-group">
              <label>
                <input type="radio" name="transport_mode" value="auto" id="transport_auto" checked>
                Calcul automatique
              </label>
              <label>
                <input type="radio" name="transport_mode" value="manuel" id="transport_manuel">
                Saisie manuelle
              </label>
            </div>
          </div>
        </div>

        <!-- Zone transport manuel -->
        <div id="zone_transport_manuel" class="zone-block hidden">
          <div class="zone-title">Transport saisi manuellement</div>
          <div class="grid2">
            <div>
              <label class="lbl">Transport poutrelles (DH/ml)</label>
              <input class="inp" type="number" step="0.01"
                     name="transport_prix_poutrelle_manuel" value="0">
            </div>
            <div>
              <label class="lbl">Transport hourdis (DH/unité)</label>
              <input class="inp" type="number" step="0.01"
                     name="transport_prix_hourdis_manuel" value="0">
            </div>
          </div>
        </div>

        <!-- Zone info transport auto -->
        <div id="zone_transport_auto_info" class="zone-block">
          <div class="zone-title">Transport automatique (simulation)</div>
          <div class="hint" id="hint_transport_auto">
            Le prix calculé par le système sera affiché ici après la lecture du CSV ou la saisie manuelle.
          </div>
        </div>
      </div>

      <!-- ================== Boutons ================== -->
      <div style="display:flex; gap:10px; margin-top:14px;">
        <button class="btn" type="submit">Générer le devis</button>
        <a class="btn btn-secondary" href="/devis/form">Réinitialiser</a>
      </div>
    </form>
  </div>

  <script>
    // --- Remplir automatiquement le nom du commercial ---
    (function () {
      const selectCode = document.getElementById("code_commercial");
      const inputNom = document.getElementById("nom_commercial");

      // Mapping code -> nom commercial généré proprement
      const mappingCommerciaux = {
        {% for code, nom in liste_commerciaux.items() %}
        "{{ code }}": "{{ nom }}"{% if not loop.last %},{% endif %}
        {% endfor %}
      };

      function updateNomCommercial() {
        const code = selectCode.value;
        inputNom.value = mappingCommerciaux[code] || "";
      }

      selectCode.addEventListener("change", updateNomCommercial);
      // init
      updateNomCommercial();
    })();

    // --- Gestion mode de saisie progiciel / manuel ---
    (function () {
      const radioProgiciel = document.getElementById("mode_progiciel");
      const radioManuel = document.getElementById("mode_manuel");
      const zoneProgiciel = document.getElementById("zone_progiciel");
      const zoneManuel = document.getElementById("zone_manuel");

      function refreshModeSaisie() {
        if (radioProgiciel.checked) {
          zoneProgiciel.classList.remove("hidden");
          zoneManuel.classList.add("hidden");
        } else {
          zoneProgiciel.classList.add("hidden");
          zoneManuel.classList.remove("hidden");
        }
      }

      radioProgiciel.addEventListener("change", refreshModeSaisie);
      radioManuel.addEventListener("change", refreshModeSaisie);
      refreshModeSaisie();
    })();

    // --- Ajout dynamique des lignes de poutrelles ---
    (function () {
      const tbody = document.getElementById("tbody_poutrelles");
      const btnAdd = document.getElementById("btn_add_poutrelle");

      function addRowPoutrelle() {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><input class="inp" name="manual_pout_type" placeholder="113, 114, 115, 135, 157"></td>
          <td><input class="inp" name="manual_pout_longueur" type="number" step="0.01" value="0"></td>
          <td><input class="inp" name="manual_pout_etrier" type="number" step="1" value="0"></td>
          <td><input class="inp" name="manual_pout_nombre" type="number" step="1" value="0"></td>
          <td><button type="button" class="btn btn-small btn-danger">X</button></td>
        `;
        tr.querySelector("button").addEventListener("click", () => tr.remove());
        tbody.appendChild(tr);
      }

      btnAdd.addEventListener("click", addRowPoutrelle);
      // au moins une ligne vide au départ
      addRowPoutrelle();
    })();

    // --- Ajout dynamique des lignes d'hourdis ---
    (function () {
      const tbody = document.getElementById("tbody_hourdis");
      const btnAdd = document.getElementById("btn_add_hourdis");

      function addRowHourdis() {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><input class="inp" name="manual_hourdis_type" placeholder="H8, H12, H16, H20, H25, H30"></td>
          <td><input class="inp" name="manual_hourdis_nombre" type="number" step="1" value="0"></td>
          <td><button type="button" class="btn btn-small btn-danger">X</button></td>
        `;
        tr.querySelector("button").addEventListener("click", () => tr.remove());
        tbody.appendChild(tr);
      }

      btnAdd.addEventListener("click", addRowHourdis);
      addRowHourdis();
    })();

    // --- Afficher / masquer les zones de transport ---
    (function () {
      const modeTransport = document.getElementById("mode_transport");
      const radioAuto = document.getElementById("transport_auto");
      const radioManuel = document.getElementById("transport_manuel");
      const zoneManuel = document.getElementById("zone_transport_manuel");
      const zoneAutoInfo = document.getElementById("zone_transport_auto_info");
      const hintAuto = document.getElementById("hint_transport_auto");
      const distanceInput = document.querySelector("input[name='distance_km']");

      function refreshTransportUI() {
        const modeTr = modeTransport.value;
        const modeCalc = radioAuto.checked ? "auto" : "manuel";

        if (modeTr === "depart") {
          // Pas de transport facturé => on masque tout le détail
          zoneManuel.classList.add("hidden");
          zoneAutoInfo.classList.add("hidden");
        } else {
          // rendu chantier
          if (modeCalc === "auto") {
            zoneManuel.classList.add("hidden");
            zoneAutoInfo.classList.remove("hidden");
          } else {
            zoneManuel.classList.remove("hidden");
            zoneAutoInfo.classList.remove("hidden");
          }
        }
      }

      modeTransport.addEventListener("change", () => {
        refreshTransportUI();
      });
      radioAuto.addEventListener("change", refreshTransportUI);
      radioManuel.addEventListener("change", refreshTransportUI);

      // Simulation transport auto en live
      async function simulateTransport() {
        const dist = parseFloat(distanceInput.value || "0");
        if (isNaN(dist) || dist <= 0) {
          hintAuto.textContent = "Distance invalide ou nulle, pas de calcul de transport.";
          return;
        }
        const body = {
          distance_km: dist,
          mode_transport: modeTransport.value,
          transport_mode: radioAuto.checked ? "auto" : "manuel",
          transport_prix_poutrelle_manuel: 0,
          transport_prix_hourdis_manuel: 0
        };
        try {
          const resp = await fetch("/simulate-transport", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
          });
          if (!resp.ok) {
            hintAuto.textContent = "Erreur lors du calcul de transport.";
            return;
          }
          const data = await resp.json();
          if (data && data.transport_total_auto) {
            hintAuto.textContent =
              "Prix calculé par le système : " +
              data.transport_total_auto.toFixed(2) +
              " DH (pour info).";
          } else {
            hintAuto.textContent =
              "Aucun transport calculé (poutrelles / hourdis vides ?).";
          }
        } catch (e) {
          hintAuto.textContent = "Erreur réseau / simulate-transport.";
        }
      }

      distanceInput.addEventListener("change", simulateTransport);
      distanceInput.addEventListener("blur", simulateTransport);

      // init
      refreshTransportUI();
    })();
  </script>
</body>
</html>
