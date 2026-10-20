/* Mecanisme transverse aux ecrans (T15) : navigation, attribution, etat dans l'URL,
   exports CSV et PNG. Insere dans chaque page par le marqueur de gabarit
   (gabarit.injecter) ; la liste des ecrans vient de partage.py.

   Il n'expose qu'un nom global, `PARTAGE`, et n'en emprunte aucun aux ecrans :
   les uns definissent `$`, `el`, `esc`, les autres non.

   Contrat d'un ecran (voir aussi partage.py) :
   - PARTAGE.demarrer({ ecran, ...D.partage })     une fois, apres le DOM ;
   - PARTAGE.lire() / PARTAGE.ecrire({ cle: val }) l'etat vit dans le fragment d'URL ;
   - PARTAGE.enregistrer(svg, { nom, colonnes, lignes })
        a la fin de chaque trace, avec les valeurs que la trace vient d'employer.
        Les lignes ne sont jamais recalculees ailleurs : un export reconstruit
        finit toujours par diverger de ce qu'on voit.

   Cles d'URL communes a tous les ecrans (un ecran ignore celles qu'il ne connait
   pas, mais ne les efface pas) :
     m  massif_id           s  saison "2021-2022"        f  fenetre (nom, fenetres.py)
     t  tranche d'altitude  v  versant du vent (nord|sud)
   x  mode de comparaison (saison|choix|massifs)   d  1 = tableaux de donnees ouverts
   Les cles propres a un ecran ne doivent pas reprendre une cle ci-dessus pour un
   autre sens. */
const PARTAGE = (() => {
  const ECRANS = __ECRANS__;
  const NS_SVG = "http://www.w3.org/2000/svg";
  const registre = new Map();            // svg -> { nom, colonnes, lignes, csv, png }
  let ecran = null, attribution = null;

  const etat = () => new URLSearchParams(location.hash.slice(1));
  const lire = () => etat();

  /* Ecrit les cles donnees (null ou "" les retire) et garde toutes les autres :
     c'est ce qui permet de passer d'un ecran a l'autre sans rien reinitialiser. */
  function ecrire(valeurs) {
    const p = etat();
    for (const k in valeurs) {
      const v = valeurs[k];
      if (v == null || v === "") p.delete(k); else p.set(k, v);
    }
    history.replaceState(null, "", "#" + p);
    liens();
  }

  /* ---------- navigation ---------- */
  function liens() {
    document.querySelectorAll(".partage-nav a[data-ecran]").forEach(a => {
      const e = ECRANS.find(x => x.id === a.dataset.ecran);
      a.href = e.fichier + location.hash;
    });
  }
  const echapper = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const dateLongue = iso => new Date(iso + "T00:00:00Z").toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });

  function style() {
    const s = document.createElement("style");
    s.textContent = `
.partage-nav{display:flex;flex-wrap:wrap;align-items:center;gap:6px 6px;padding:14px 0 0;font-size:13px}
.partage-nav a,.partage-nav button{font:inherit;color:var(--ink-2,#4d5765);background:var(--surface,#fff);border:1px solid var(--rule,#d7dce2);border-radius:6px;padding:4px 10px;text-decoration:none;cursor:pointer}
.partage-nav a[aria-current="page"]{background:var(--s1,#2a78d6);border-color:var(--s1,#2a78d6);color:#fff}
.partage-nav .espace{flex:1 1 auto}
.exports{display:flex;gap:6px;justify-content:flex-end;margin:2px 0 0;font-size:12px}
.exports a,.exports button{font:inherit;color:var(--ink-2,#4d5765);background:none;border:1px solid var(--rule,#d7dce2);border-radius:5px;padding:1px 8px;text-decoration:none;cursor:pointer}
.exports a:hover,.exports button:hover,.partage-nav a:hover,.partage-nav button:hover{color:var(--ink,#10141a)}
:is(.exports a,.exports button,.partage-nav a,.partage-nav button):focus-visible{outline:2px solid var(--s1,#2a78d6);outline-offset:2px}
.attribution a{color:inherit}`;
    document.head.appendChild(s);
  }

  /* Barre de navigation, pied d'attribution, lien copiable. `donnees`, `archive`,
     `genere`, `contours` viennent de partage.bloc() dans le payload. */
  function demarrer(o) {
    ecran = o.ecran;
    attribution = o;
    style();
    const racine = document.querySelector(".wrap") || document.body;
    const nav = document.createElement("nav");
    nav.className = "partage-nav";
    nav.setAttribute("aria-label", "Écrans");
    nav.innerHTML = ECRANS.map(e =>
      `<a data-ecran="${e.id}" href="${e.fichier}"${e.id === ecran ? ' aria-current="page"' : ""}>${echapper(e.libelle)}</a>`).join("")
      + `<span class="espace"></span><button type="button" id="partage-copier">Copier le lien</button>`;
    racine.insertBefore(nav, racine.firstChild);
    nav.querySelector("#partage-copier").addEventListener("click", ev => {
      const b = ev.currentTarget;
      const ok = () => { b.textContent = "Lien copié"; setTimeout(() => { b.textContent = "Copier le lien"; }, 1800); };
      if (navigator.clipboard) navigator.clipboard.writeText(location.href).then(ok, () => {});
    });
    liens();
    addEventListener("hashchange", liens);

    const pied = document.getElementById("attribution");
    if (pied) {
      pied.className = "attribution";
      pied.innerHTML = `${echapper(o.donnees)}` + (o.archive ? ` · archive arrêtée au ${dateLongue(o.archive)}` : "")
        + ` · page générée le ${dateLongue(o.genere)}`
        + (o.contours ? ` · ${echapper(o.contours)}` : "")
        + ` · <a href="${o.source_url}">source</a>, <a href="${o.licence_url}">licence</a>`;
    }
    /* Sur la carte, l'attribution des contours est aussi sous la carte (spec section 7). */
    const sousCarte = document.getElementById("attribution-contours");
    if (sousCarte && o.contours) sousCarte.textContent = `${o.donnees}, archive arrêtée au ${dateLongue(o.archive)}. ${o.contours}.`;
  }

  /* ---------- exports ---------- */
  const cellule = v => {
    if (v == null) return "";
    const s = String(v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  /* Les lignes `#` portent l'attribution : un export est une reutilisation, et la
     Licence Ouverte demande la mention de la source et de sa date. Les lecteurs de
     CSV courants les sautent (pandas comment="#", polars comment_prefix="#"). */
  function texteCsv(d) {
    const tete = [
      `# ${d.titre || d.nom}`,
      `# ${attribution.donnees}` + (attribution.archive ? `, archive arrêtée au ${attribution.archive}` : ""),
      `# ${location.href}`,
    ];
    return "﻿" + [...tete, d.colonnes.map(cellule).join(","), ...d.lignes.map(l => l.map(cellule).join(","))].join("\r\n") + "\r\n";
  }
  const nomFichier = (nom, ext) => `bra-${ecran}-${nom}.${ext}`.replace(/[^\w.-]+/g, "-");

  function barre(svg) {
    const hote = svg.closest(".plot") || svg.parentNode;
    let b = hote.nextElementSibling;
    if (b && b.classList.contains("exports")) return b;
    b = document.createElement("div");
    b.className = "exports";
    b.innerHTML = `<a class="exp-csv" role="button">Exporter CSV</a><button type="button" class="exp-png">Exporter PNG</button>`;
    hote.insertAdjacentElement("afterend", b);
    b.querySelector(".exp-png").addEventListener("click", () => {
      const d = registre.get(svg);
      png(svg).then(url => telecharger(url, nomFichier(d ? d.nom : "graphe", "png")));
    });
    return b;
  }
  function telecharger(url, fichier) {
    const a = document.createElement("a");
    a.href = url; a.download = fichier;
    document.body.appendChild(a); a.click(); a.remove();
  }

  /* Enregistre les donnees d'un graphe. A appeler a chaque trace : le lien CSV est
     remplace, il reflete donc toujours l'etat affiche (filtres compris).
     colonnes : [nom, ...] ; lignes : [[valeur, ...], ...] en valeurs brutes
     (nombres non formates, decimale au point, null = vide). */
  function enregistrer(svg, d) {
    if (typeof svg === "string") svg = document.getElementById(svg);
    if (!svg) return;
    registre.set(svg, d);
    const a = barre(svg).querySelector(".exp-csv");
    a.href = "data:text/csv;charset=utf-8," + encodeURIComponent(texteCsv(d));
    a.download = nomFichier(d.nom, "csv");
    a.dataset.lignes = d.lignes.length;
  }

  /* PNG : le SVG de la page s'appuie sur des variables CSS et des classes qui
     n'existent pas une fois l'image sortie de la page. On recopie donc les
     proprietes calculees de chaque noeud, puis on ajoute un titre et l'attribution
     sur fond plein. Retourne une promesse de data URL. */
  const PROPS = ["fill", "stroke", "stroke-width", "stroke-dasharray", "stroke-linejoin", "stroke-linecap", "opacity",
    "fill-opacity", "stroke-opacity", "font-family", "font-size", "font-weight", "text-anchor", "dominant-baseline", "letter-spacing"];
  function figer(origine, copie) {
    const cs = getComputedStyle(origine);
    for (const p of PROPS) copie.style.setProperty(p, cs.getPropertyValue(p));
    const a = origine.children, b = copie.children;
    for (let i = 0; i < a.length; i++) figer(a[i], b[i]);
  }
  function png(svg) {
    const r = svg.getBoundingClientRect();
    const vb = svg.viewBox && svg.viewBox.baseVal;
    const L = vb && vb.width ? vb.width : Math.round(r.width), H = vb && vb.height ? vb.height : Math.round(r.height);
    const copie = svg.cloneNode(true);
    figer(svg, copie);
    copie.querySelectorAll("title").forEach(t => t.remove());
    copie.setAttribute("x", 0); copie.setAttribute("y", 30);
    copie.setAttribute("width", L); copie.setAttribute("height", H);
    copie.setAttribute("viewBox", `0 0 ${L} ${H}`);
    const cs = getComputedStyle(document.body);
    const fond = cs.getPropertyValue("background-color"), encre = cs.getPropertyValue("color");
    const titre = (svg.closest(".panel") || document).querySelector("h2");
    const d = registre.get(svg);
    const pied = `${attribution.donnees}` + (attribution.archive ? `, archive arrêtée au ${attribution.archive}` : "");
    const EXTRA = attribution.contours ? 68 : 54;       // une ligne de plus pour les contours : sinon elle deborde
    const ext = document.createElementNS(NS_SVG, "svg");
    ext.setAttribute("xmlns", NS_SVG);
    ext.setAttribute("width", L); ext.setAttribute("height", H + EXTRA);
    ext.setAttribute("viewBox", `0 0 ${L} ${H + EXTRA}`);
    const fondR = document.createElementNS(NS_SVG, "rect");
    fondR.setAttribute("width", L); fondR.setAttribute("height", H + EXTRA); fondR.setAttribute("fill", fond);
    ext.appendChild(fondR);
    const texte = (y, taille, s, op) => {
      const t = document.createElementNS(NS_SVG, "text");
      t.setAttribute("x", 12); t.setAttribute("y", y);
      t.setAttribute("font-size", taille); t.setAttribute("fill", encre);
      t.setAttribute("font-family", "system-ui, sans-serif"); t.setAttribute("opacity", op);
      t.textContent = s; ext.appendChild(t);
    };
    texte(20, 15, ((d && d.titre) || (titre ? titre.textContent : "")), 1);
    ext.appendChild(copie);
    texte(H + 46, 11, pied, .7);
    if (attribution.contours) texte(H + 61, 11, attribution.contours, .7);
    const xml = new XMLSerializer().serializeToString(ext);
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const c = document.createElement("canvas");
        c.width = L * 2; c.height = (H + EXTRA) * 2;
        const g = c.getContext("2d");
        g.scale(2, 2); g.drawImage(img, 0, 0, L, H + EXTRA);
        resolve(c.toDataURL("image/png"));
      };
      img.onerror = () => reject(new Error("rasterisation impossible"));
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
    });
  }

  return { demarrer, lire, ecrire, enregistrer, png, registre };
})();
